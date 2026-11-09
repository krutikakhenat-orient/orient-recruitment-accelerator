"""Builds a draft question set from grouped JDs and a resume. Output is a draft: a human approves it."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from .config import Settings
from .llm import LanguageModelError
from .models import PlanQuestionsRequest, Question, QuestionSet, QuestionSource
from .ports import LanguageModel
from .prompts import PLANNER_SYSTEM, PROMPT_VERSION
from .safety import (
    mentions_protected_topic,
    redact_resume_for_model,
    sanitise_untrusted,
    wrap_untrusted,
)

log = logging.getLogger(__name__)

_INTRO = Question(
    id="std-intro",
    text="To begin, please introduce yourself and tell us about the experience "
    "you consider most relevant to this role.",
    competency="introduction",
    source=QuestionSource.STANDARD,
    follow_up_allowed=False,
)
_WRAP = Question(
    id="std-wrap",
    text="Is there anything about your experience that we have not covered and you would like to add?",
    competency="closing",
    source=QuestionSource.STANDARD,
    follow_up_allowed=False,
)


class _LlmQuestion(BaseModel):
    model_config = ConfigDict(extra="ignore")
    text: str
    competency: str = "general"
    source: str = "job_description"
    evidence_ref: str | None = None


class _LlmPlan(BaseModel):
    model_config = ConfigDict(extra="ignore")
    questions: list[_LlmQuestion]


def extract_json_object(raw: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply. Raises ValueError if absent/invalid."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no_json_object")
    parsed = json.loads(raw[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("json_not_object")
    return parsed


class QuestionPlanner:
    def __init__(self, llm: LanguageModel, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def plan(self, request: PlanQuestionsRequest) -> QuestionSet:
        limit = request.max_questions or self._settings.max_questions
        jd_blocks: list[str] = []
        for jd in request.job_descriptions:
            clean = sanitise_untrusted(jd.text, max_chars=8000)
            skills = ", ".join(jd.must_have_skills)
            jd_blocks.append(
                wrap_untrusted(
                    f"JD_{jd.jd_id}", f"Title: {jd.title}\nMust-have skills: {skills}\n{clean.text}"
                )
            )
        resume = redact_resume_for_model(request.resume.text)
        prompt = (
            f"Write up to {limit} interview questions.\n\n"
            + "\n\n".join(jd_blocks)
            + "\n\n"
            + wrap_untrusted("RESUME", resume.text)
        )

        questions: list[Question] = []
        generated_by = "llm"
        try:
            raw = self._llm.complete(
                system=PLANNER_SYSTEM,
                user=prompt,
                max_tokens=self._settings.llm_batch_max_tokens,
                temperature=0.3,
            )
            questions = self._parse(raw, limit)
        except (LanguageModelError, ValueError, ValidationError) as exc:
            log.warning("planner_llm_failed", extra={"error": type(exc).__name__})
        if not questions:
            generated_by = "deterministic_fallback"
            questions = self._fallback(request, limit)

        final = [_INTRO, *questions, _WRAP]
        for index, question in enumerate(final):
            if question.source is not QuestionSource.STANDARD:
                final[index] = question.model_copy(update={"id": f"q{index}"})
        return QuestionSet(
            interview_id=request.interview_id,
            candidate_ref=request.resume.candidate_ref,
            version=self._version(request, limit, generated_by),
            questions=final,
            generated_by=generated_by,  # type: ignore[arg-type]
            model_id=self._llm.model_id if generated_by == "llm" else None,
            prompt_version=PROMPT_VERSION,
        )

    def _parse(self, raw: str, limit: int) -> list[Question]:
        plan = _LlmPlan.model_validate(extract_json_object(raw))
        seen: set[str] = set()
        out: list[Question] = []
        for item in plan.questions:
            text = re.sub(r"\s+", " ", item.text).strip()
            key = text.lower()
            if (
                not (5 <= len(text) <= 400)
                or key in seen
                or mentions_protected_topic(text)
                or sanitise_untrusted(text, max_chars=400).flags
            ):
                continue
            seen.add(key)
            source = (
                QuestionSource.RESUME if item.source == "resume" else QuestionSource.JOB_DESCRIPTION
            )
            out.append(
                Question(
                    id="tmp",
                    text=text,
                    competency=(item.competency or "general")[:80],
                    source=source,
                    evidence_ref=(item.evidence_ref or None) and item.evidence_ref[:300],
                )
            )
            if len(out) == limit:
                break
        return out

    def _fallback(self, request: PlanQuestionsRequest, limit: int) -> list[Question]:
        skills: list[str] = []
        for jd in request.job_descriptions:
            for skill in jd.must_have_skills:
                cleaned = re.sub(r"\s+", " ", skill).strip()
                if cleaned and cleaned.lower() not in {s.lower() for s in skills}:
                    skills.append(cleaned)
        out = [
            Question(
                id="tmp",
                text=f"Can you describe a project where you used {skill}, and what your own role was?",
                competency=skill,
                source=QuestionSource.JOB_DESCRIPTION,
                evidence_ref=f"JD must-have skill: {skill}",
            )
            for skill in skills
            if not mentions_protected_topic(skill)
        ]
        if not out:
            title = request.job_descriptions[0].title
            out = [
                Question(
                    id="tmp",
                    text=f"What past work do you think best prepares you for the {title} role?",
                    competency="role_fit",
                    source=QuestionSource.JOB_DESCRIPTION,
                    evidence_ref=f"JD title: {title}",
                )
            ]
        return out[:limit]

    def _version(self, request: PlanQuestionsRequest, limit: int, generated_by: str) -> str:
        payload = {
            "prompt_version": PROMPT_VERSION,
            "generated_by": generated_by,
            "limit": limit,
            "jds": [jd.model_dump() for jd in request.job_descriptions],
            "resume": request.resume.model_dump(),
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return digest[:16]

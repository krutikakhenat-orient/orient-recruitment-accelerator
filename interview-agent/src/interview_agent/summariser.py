"""Advisory interview summary. Output is validated; every quote must be verbatim from the transcript."""

from __future__ import annotations

import logging
import re
from collections import defaultdict

from pydantic import ValidationError

from .config import Settings
from .llm import LanguageModelError
from .models import (
    Coverage,
    EndReason,
    InterviewSummary,
    Question,
    QuestionAssessment,
    Speaker,
)
from .orchestrator import InterviewOrchestrator
from .planner import extract_json_object
from .ports import LanguageModel
from .prompts import PROMPT_VERSION, SUMMARY_SYSTEM
from .safety import contains_verdict_language, mentions_protected_topic, wrap_untrusted

log = logging.getLogger(__name__)

_MIN_WORDS_FOR_CONFIDENT_ANSWER = 15
_MAX_QUOTE_CHARS = 300


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


class InterviewSummariser:
    def __init__(self, llm: LanguageModel, settings: Settings) -> None:
        self._llm = llm
        self._settings = settings

    def summarise(self, run: InterviewOrchestrator) -> InterviewSummary:
        answers: dict[str, list[str]] = defaultdict(list)
        for turn in run.turns:
            if turn.speaker is Speaker.CANDIDATE and turn.question_id:
                answers[turn.question_id].append(turn.text)
        injected_in = {
            t.question_id
            for t in run.turns
            if t.speaker is Speaker.CANDIDATE and "possible_prompt_injection" in t.flags
        }

        llm_data: dict[str, object] = {}
        generated_by = "llm"
        answered_ids = [q.id for q in run.question_set.questions if answers.get(q.id)]
        if answered_ids:
            try:
                llm_data = self._call_llm(run, answers)
            except (LanguageModelError, ValueError, ValidationError) as exc:
                log.warning("summary_llm_failed", extra={"error": type(exc).__name__})
        if not llm_data:
            generated_by = "deterministic_fallback"

        llm_by_id: dict[str, dict[str, object]] = {}
        raw_assessments = llm_data.get("assessments")
        if isinstance(raw_assessments, list):
            for item in raw_assessments:
                if isinstance(item, dict) and isinstance(item.get("question_id"), str):
                    llm_by_id[item["question_id"]] = item

        flags = list(run.integrity_flags)
        assessments: list[QuestionAssessment] = []
        for question in run.question_set.questions:
            assessments.append(
                self._assess(
                    question,
                    answers.get(question.id, []),
                    llm_by_id.get(question.id),
                    skipped=question.id in run.skipped_question_ids,
                    asked=question.id in run.asked_question_ids,
                    injection=question.id in injected_in,
                    flags=flags,
                )
            )

        overview = self._clean_text(llm_data.get("overview"), flags, "overview")
        if not overview:
            overview = (
                "An automated summary could not be produced. Please read the transcript."
                if generated_by == "deterministic_fallback"
                else "See the per-question notes and the transcript."
            )
        topics = [
            t.strip()[:200]
            for t in _as_str_list(llm_data.get("topics_to_probe_next"))
            if t.strip() and not mentions_protected_topic(t) and not contains_verdict_language(t)
        ][:8]
        for extra in _as_str_list(llm_data.get("integrity_flags")):
            note = f"model_noted:{extra.strip()[:120]}"
            if extra.strip() and note not in flags:
                flags.append(note)

        end_reason = run.end_reason or EndReason.ERROR
        return InterviewSummary(
            interview_id=run.interview_id,
            candidate_ref=run.question_set.candidate_ref,
            question_set_version=run.question_set.version,
            generated_by=generated_by,  # type: ignore[arg-type]
            model_id=self._llm.model_id if generated_by == "llm" else None,
            prompt_version=PROMPT_VERSION,
            duration_seconds=run.elapsed_seconds,
            end_reason=end_reason,
            overview=overview,
            assessments=assessments,
            topics_to_probe_next=topics,
            integrity_flags=flags,
        )

    # ------------------------------------------------------------ internals

    def _call_llm(
        self, run: InterviewOrchestrator, answers: dict[str, list[str]]
    ) -> dict[str, object]:
        blocks: list[str] = []
        for question in run.question_set.questions:
            if question.id not in answers:
                continue
            body = "\n".join(answers[question.id])
            blocks.append(
                f"question_id: {question.id}\nquestion: {question.text}\n"
                + wrap_untrusted(f"ANSWER_{question.id}", body)
            )
        raw = self._llm.complete(
            system=SUMMARY_SYSTEM,
            user="Summarise this interview.\n\n" + "\n\n".join(blocks),
            max_tokens=self._settings.llm_batch_max_tokens,
            temperature=0.1,
        )
        return extract_json_object(raw)

    def _assess(
        self,
        question: Question,
        answer_parts: list[str],
        llm_item: dict[str, object] | None,
        *,
        skipped: bool,
        asked: bool,
        injection: bool,
        flags: list[str],
    ) -> QuestionAssessment:
        if not asked:
            return QuestionAssessment(
                question_id=question.id,
                question_text=question.text,
                coverage=Coverage.NOT_ASKED,
                answer_summary="This question was not reached.",
                needs_human_review=True,
                review_reason="Not asked before the interview ended.",
            )
        if skipped:
            return QuestionAssessment(
                question_id=question.id,
                question_text=question.text,
                coverage=Coverage.SKIPPED,
                answer_summary="The candidate chose to skip this question.",
                needs_human_review=False,
            )
        answer_text = " ".join(answer_parts)
        word_count = len(answer_text.split())
        if word_count == 0:
            return QuestionAssessment(
                question_id=question.id,
                question_text=question.text,
                coverage=Coverage.PARTIALLY_ANSWERED,
                answer_summary="No answer was captured for this question.",
                needs_human_review=True,
                review_reason="No answer captured; this is not evidence about the candidate.",
            )

        summary = self._clean_text(
            llm_item.get("answer_summary") if llm_item else None, flags, question.id
        )
        coverage = (
            Coverage.ANSWERED
            if word_count >= _MIN_WORDS_FOR_CONFIDENT_ANSWER
            else Coverage.PARTIALLY_ANSWERED
        )
        if llm_item and llm_item.get("coverage") == "partially_answered":
            coverage = Coverage.PARTIALLY_ANSWERED
        if not summary:
            summary = f'Answer begins: "{answer_text[:200].strip()}" (see transcript).'

        haystack = _norm(answer_text)
        quotes = [
            q.strip()
            for q in _as_str_list(llm_item.get("evidence_quotes") if llm_item else None)
            if 0 < len(q.strip()) <= _MAX_QUOTE_CHARS and _norm(q) in haystack
        ][:3]

        reasons: list[str] = []
        if coverage is not Coverage.ANSWERED:
            reasons.append("Short or partial answer; missing detail is not proof of absence.")
        if injection:
            reasons.append("Answer contained text that tried to influence the evaluation.")
        return QuestionAssessment(
            question_id=question.id,
            question_text=question.text,
            coverage=coverage,
            answer_summary=summary,
            evidence_quotes=quotes,
            needs_human_review=bool(reasons),
            review_reason=" ".join(reasons) or None,
        )

    @staticmethod
    def _clean_text(value: object, flags: list[str], where: str) -> str:
        if not isinstance(value, str) or not value.strip():
            return ""
        text = value.strip()[:1500]
        if contains_verdict_language(text) or mentions_protected_topic(text):
            flag = f"summary_text_removed:{where}"
            if flag not in flags:
                flags.append(flag)
            return ""
        return text


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, str)]

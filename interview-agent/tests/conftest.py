"""Shared fixtures. All data is SYNTHETIC: no real candidate or employer information."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest

from interview_agent.config import Settings
from interview_agent.models import (
    JobDescriptionPayload,
    PlanQuestionsRequest,
    Question,
    QuestionSet,
    QuestionSource,
    ResumePayload,
)

SYNTHETIC_RESUME = (
    "SYNTHETIC RESUME. Candidate Test-001\n"
    "Date of Birth: 01/01/1990\nGender: synthetic\n"
    "Email: test.person@example.invalid  Phone: +91 90000 00000\n"
    "Experience: built Python REST services with FastAPI and PostgreSQL for 4 years.\n"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="local",
        adapters="fake",
        output_dir=str(tmp_path / "out"),
        endpoint_silence_ms=10,
        idle_prompt_seconds=3600,
    )


@pytest.fixture
def interview_id() -> UUID:
    return uuid4()


@pytest.fixture
def plan_request(interview_id: UUID) -> PlanQuestionsRequest:
    return PlanQuestionsRequest(
        interview_id=interview_id,
        job_descriptions=[
            JobDescriptionPayload(
                jd_id="jd-1",
                title="Synthetic Backend Engineer",
                text="Build APIs in Python. Experience with PostgreSQL required.",
                must_have_skills=["Python", "PostgreSQL"],
            )
        ],
        resume=ResumePayload(candidate_ref="cand-001", text=SYNTHETIC_RESUME),
    )


@pytest.fixture
def question_set(interview_id: UUID) -> QuestionSet:
    return QuestionSet(
        interview_id=interview_id,
        candidate_ref="cand-001",
        version="v-test",
        generated_by="deterministic_fallback",
        prompt_version="test",
        approved=True,
        approved_by="hr-001",
        questions=[
            Question(
                id="std-intro",
                text="Please introduce yourself briefly.",
                source=QuestionSource.STANDARD,
                follow_up_allowed=False,
            ),
            Question(
                id="q1",
                text="Describe a project where you used Python.",
                source=QuestionSource.JOB_DESCRIPTION,
            ),
            Question(
                id="q2",
                text="How do you design database schemas?",
                source=QuestionSource.JOB_DESCRIPTION,
            ),
        ],
    )


LONG_ANSWER = " ".join(["I designed and delivered the service end to end with tests"] * 4)

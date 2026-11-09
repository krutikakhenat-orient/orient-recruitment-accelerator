"""Developer CLI for exercising the agent without audio.

  interview-agent plan --input plan_request.json            # draft questions from JD + resume
  interview-agent chat --question-set qs.json --role "..."  # typed interview in the terminal

Set INTERVIEW_AGENT_ADAPTERS=fake to run with no AWS calls.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import get_settings
from .models import EndReason, InterviewRecord, PlanQuestionsRequest, QuestionSet
from .orchestrator import InterviewOrchestrator, InterviewState
from .runtime import build_runtime


def _plan(args: argparse.Namespace) -> int:
    runtime = build_runtime(get_settings())
    request = PlanQuestionsRequest.model_validate_json(Path(args.input).read_text("utf-8"))
    question_set = runtime.planner.plan(request)
    sys.stdout.write(question_set.model_dump_json(indent=2) + "\n")
    return 0


def _chat(args: argparse.Namespace) -> int:
    settings = get_settings()
    runtime = build_runtime(settings)
    question_set = QuestionSet.model_validate_json(Path(args.question_set).read_text("utf-8"))
    if not question_set.approved:
        question_set = question_set.model_copy(update={"approved": True, "approved_by": "cli-dev"})
        sys.stdout.write("[dev] question set auto-approved for this local run\n")
    run = InterviewOrchestrator(
        interview_id=question_set.interview_id,
        question_set=question_set,
        role_title=args.role,
        llm=runtime.llm,
        settings=settings,
    )
    for line in run.opening():
        sys.stdout.write(f"AGENT: {line}\n")
    while run.state is InterviewState.ASKING:
        try:
            answer = input("YOU:   ")
        except EOFError:
            run.mark_ended(EndReason.CANDIDATE_DISCONNECTED)
            break
        for line in run.handle_candidate_utterance(answer):
            sys.stdout.write(f"AGENT: {line}\n")
    summary = runtime.summariser.summarise(run)
    record = InterviewRecord(summary=summary, transcript=run.turns)
    location = runtime.sink.persist(record)
    sys.stdout.write(f"\nSaved to {location}\n")
    sys.stdout.write(summary.model_dump_json(indent=2) + "\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="interview-agent")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--input", required=True)
    plan.set_defaults(func=_plan)
    chat = sub.add_parser("chat")
    chat.add_argument("--question-set", required=True)
    chat.add_argument("--role", default="the open")
    chat.set_defaults(func=_chat)
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

"""Question checks before retrieval (Req 4.6, 5.3, 8.1).

- Self-service guard: questions about the asker's own records (leave balance, pay, ...)
  are not answered from policy; the reply points to where that data is held.
- PII scrub: emails, phone-like and ID-like numbers are masked before a question is logged.
- Guardrail: with Bedrock on, the question goes through the configured Bedrock Guardrail.
  Without Bedrock a no-op guard is used (the local scrub still applies to logs).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

log = logging.getLogger(__name__)

_SELF_SERVICE = re.compile(
    r"\b(my|mine)\s+(own\s+)?("
    r"leave\s+balance|remaining\s+leaves?|leaves?\s+left|salary|pay\s*slips?|pay|ctc|bonus|"
    r"attendance|appraisal|rating|increment|pf|provident\s+fund|tax|tds|form\s*16|"
    r"reimbursements?|claims?|bank\s+details?|records?"
    r")\b"
    r"|\bhow\s+many\s+(leaves?|leave\s+days|days\s+(off|of\s+leave))\s+(do|have)\s+i\b"
    r"|\b(do|have)\s+i\s+(have\s+)?(any\s+)?(leaves?|leave\s+days)\s+(left|remaining)\b",
    re.IGNORECASE,
)

SELF_SERVICE_REPLY = (
    "I can't see personal records such as your leave balance, pay or attendance. Please "
    "check the HR system where your records are kept (placeholder: HRMS link not configured), "
    "or send this question to HR."
)

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+")
_PAN = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.IGNORECASE)
_NUMBER = re.compile(r"\+?\d[\d\s-]{7,}\d")


def is_self_service(question: str) -> bool:
    return bool(_SELF_SERVICE.search(question))


# Greetings and thanks: not policy questions, so no search and no model call. Reply kindly
# instead of "not found" (users typing "hi" thought the chatbot was broken).
_SMALL_TALK = re.compile(
    r"^\s*(hi+|hello+|hey+|hiya|namaste|good\s+(morning|afternoon|evening)|"
    r"thanks?|thank\s+you|thx|ok(ay)?|cool|great|bye|goodbye)"
    r"(\s+(there|hr|team|bot|all))?\s*[!.?,:)]*\s*$",
    re.IGNORECASE,
)

GREETING_REPLY = (
    "Hello! I answer questions from the company's approved HR policies. Try asking, for "
    "example, how many days of annual leave you get, what the working hours are, or what to "
    "do in your first week."
)
THANKS_REPLY = "You're welcome. Ask me anything else about company HR policies."


def small_talk_reply(question: str) -> str | None:
    m = _SMALL_TALK.match(question)
    if not m:
        return None
    word = m.group(1).lower()
    if word.startswith(("thank", "thx", "ok", "cool", "great", "bye", "goodbye")):
        return THANKS_REPLY
    return GREETING_REPLY


def scrub_pii(text: str) -> str:
    text = _EMAIL.sub("[email]", text)
    text = _PAN.sub("[id]", text)
    return _NUMBER.sub("[number]", text)


@dataclass(frozen=True)
class GuardResult:
    allowed: bool
    reason: str | None = None


class QuestionGuard(Protocol):
    def check(self, question: str) -> GuardResult: ...


class NoopGuard:
    def check(self, question: str) -> GuardResult:
        return GuardResult(allowed=True)


class BedrockGuardrail:
    """Bedrock ApplyGuardrail on the INPUT. If the guardrail service fails, the question is
    allowed (logged): the answer path is still limited to approved passages, and the
    generation call carries the same guardrail."""

    def __init__(self, client: Any, guardrail_id: str, guardrail_version: str) -> None:
        self._client = client
        self._id = guardrail_id
        self._version = guardrail_version

    def check(self, question: str) -> GuardResult:
        try:
            response = self._client.apply_guardrail(
                guardrailIdentifier=self._id, guardrailVersion=self._version, source="INPUT",
                content=[{"text": {"text": question}}],
            )
        except Exception as exc:  # botocore errors
            log.warning("assistant.guardrail_unavailable", extra={"error": type(exc).__name__})
            return GuardResult(allowed=True)
        if response.get("action") == "GUARDRAIL_INTERVENED":
            return GuardResult(allowed=False, reason="guardrail")
        return GuardResult(allowed=True)


GUARDRAIL_REPLY = (
    "I can't help with that question here. Please contact HR directly."
)

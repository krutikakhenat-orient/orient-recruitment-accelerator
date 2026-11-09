"""Handling of untrusted text (JDs, resumes, candidate speech) and guarding of agent output.

Rationale: documents and speech are data, never instructions. We neutralise them before they
reach the model, flag injection attempts for a human, keep protected characteristics out of
the interview, and stop the agent from voicing anything that sounds like a decision.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"ignore\s+(all\s+|any\s+|the\s+)?(previous|prior|above|earlier)\s+(instructions?|prompts?|rules?)",
        r"disregard\s+.{0,40}(instructions?|rules?|prompt)",
        r"(reveal|show|print|repeat)\s+.{0,30}(system\s+prompt|instructions|your\s+rules)",
        r"you\s+are\s+now\s+(a|an|the)\b",
        r"</?\s*(system|assistant|developer)\s*>",
        r"\bnew\s+instructions?\s*:",
        r"(rate|score|rank|mark)\s+(me|this\s+candidate)\s+.{0,20}(highest|10|top|perfect|hire)",
        r"(recommend|select|hire)\s+(me|this\s+candidate)\b",
    )
]

# Characteristics that must never be asked about or influence the interview.
_PROTECTED_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bage\b|\bhow\s+old\b|date\s+of\s+birth|\bdob\b|\bbirthday\b",
        r"\bmarri(ed|age)\b|marital|\bspouse\b|\bhusband\b|\bwife\b|\bboyfriend\b|\bgirlfriend\b",
        r"pregnan|maternity|(your|have|any)\s+(children|kids)\b|family\s+(plans|status|members|background)",
        r"relig|\bcaste\b|\bethnic|\brace\b(?!\s+condition)|\bnationality\b|skin\s+colou?r",
        r"disabilit|medical\s+(condition|history|issue|problem)|health\s+(condition|issue|problem)"
        r"|illness|mental\s+health|vaccin",
        r"sexual|\bgender\b|\bLGBT|orientation",
        r"photograph|\bhobbies\b|\bhobby\b",
    )
]

# Lines in resumes that carry protected attributes are dropped before any model sees them.
_PROTECTED_LINE = re.compile(
    r"^\s*(date\s+of\s+birth|d\.?o\.?b\.?|age|gender|sex|marital\s+status|religion|caste|"
    r"nationality|father'?s?\s+name|mother'?s?\s+name|hobbies|blood\s+group)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+\.[\w.\-]+")
_PHONE = re.compile(r"(?<!\w)(\+?\d[\d\s().\-]{8,}\d)(?!\w)")
_URL = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)

_DECISION_LANGUAGE = re.compile(
    r"\b(you(\s+are|'re)\s+(hired|selected|rejected|not\s+selected|unfit|a\s+good\s+fit|"
    r"not\s+a\s+good\s+fit)|we\s+will\s+(hire|reject)|bad\s+candidate|unfit|"
    r"you\s+(passed|failed)|your\s+score|you\s+scored|congratulations)\b",
    re.IGNORECASE,
)
_SUMMARY_VERDICT_LANGUAGE = re.compile(
    r"\b(unfit|bad\s+candidate|not\s+suitable|should\s+(be\s+)?(hire|reject)d?|"
    r"recommend(ed)?\s+(to\s+)?(hire|reject)|reject(ed)?\s+(the\s+)?candidate|"
    r"hire\s+(the\s+)?candidate|overall\s+score|rating\s*:)\b",
    re.IGNORECASE,
)

_CONTROL_AND_HIDDEN = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")

SAFE_FALLBACK_LINE = "Thank you. Let's continue."


@dataclass(frozen=True)
class Sanitised:
    text: str
    flags: list[str] = field(default_factory=list)


def _strip_control(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = _CONTROL_AND_HIDDEN.sub("", text)
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def sanitise_untrusted(text: str, *, max_chars: int) -> Sanitised:
    """Normalise, strip hidden characters, truncate and flag suspicious content."""
    flags: list[str] = []
    raw_len = len(text)
    cleaned = _strip_control(text)
    if len(cleaned) != raw_len and raw_len - len(cleaned) > 5:
        flags.append("hidden_or_control_characters_removed")
    if any(p.search(cleaned) for p in _INJECTION_PATTERNS):
        flags.append("possible_prompt_injection")
    words = re.findall(r"[a-zA-Z]{4,}", cleaned.lower())
    if len(words) >= 60:
        top, count = Counter(words).most_common(1)[0]
        if count >= 20 and count / len(words) > 0.08:
            flags.append(f"possible_keyword_stuffing:{top}")
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
        flags.append("truncated")
    return Sanitised(cleaned.strip(), flags)


def redact_resume_for_model(text: str, *, max_chars: int = 12000) -> Sanitised:
    """Minimise a resume before it is sent to the model: no contact details, no protected lines."""
    base = sanitise_untrusted(text, max_chars=max_chars)
    redacted = _PROTECTED_LINE.sub("", base.text)
    redacted = _EMAIL.sub("[email]", redacted)
    redacted = _URL.sub("[link]", redacted)
    redacted = _PHONE.sub("[phone]", redacted)
    return Sanitised(re.sub(r"\n{3,}", "\n\n", redacted).strip(), base.flags)


def mentions_protected_topic(text: str) -> bool:
    return any(p.search(text) for p in _PROTECTED_PATTERNS)


def wrap_untrusted(label: str, text: str) -> str:
    """Fence untrusted text so the prompt can state it is data. Delimiter collisions are removed."""
    safe = text.replace("<<<", "<").replace(">>>", ">")
    return f"<<<{label}\n{safe}\n{label}>>>"


@dataclass(frozen=True)
class GuardResult:
    text: str
    blocked: bool
    reason: str | None = None


def guard_spoken_output(text: str, *, max_chars: int = 400) -> GuardResult:
    """Last check before text is spoken to a candidate."""
    cleaned = re.sub(r"[*_`#>|]+", "", _strip_control(text))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return GuardResult(SAFE_FALLBACK_LINE, True, "empty_output")
    if _DECISION_LANGUAGE.search(cleaned):
        return GuardResult(SAFE_FALLBACK_LINE, True, "decision_language")
    if mentions_protected_topic(cleaned):
        return GuardResult(SAFE_FALLBACK_LINE, True, "protected_topic")
    if re.search(r"https?://|www\.", cleaned, re.IGNORECASE):
        return GuardResult(SAFE_FALLBACK_LINE, True, "url_in_output")
    if len(cleaned) > max_chars:
        cut = cleaned[:max_chars]
        end = max(cut.rfind("."), cut.rfind("?"), cut.rfind("!"))
        cleaned = cut[: end + 1] if end > 40 else cut
    return GuardResult(cleaned, False)


def contains_verdict_language(text: str) -> bool:
    return bool(_SUMMARY_VERDICT_LANGUAGE.search(text))

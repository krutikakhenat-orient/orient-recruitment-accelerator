"""Resume field extraction with provenance and confidence (Req 5.3).

Deterministic, pattern-based extraction of a few well-defined fields (email, phone, years
of experience). It treats resume text purely as data:

- It never interprets instruction-like text ("ignore previous instructions", "system:")
  as commands; such content is flagged, not executed (AI-safety, steering/responsible-ai).
- It detects likely hidden-text / keyword-stuffing (very long whitespace-free runs, or an
  improbable density of a single token) and flags low confidence for human review rather
  than trusting it.
- It never infers a qualification from loosely related wording.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# Phone digits may be separated by spaces or hyphens but must NOT span line breaks
# (a greedy match across newlines would wrongly swallow following numbers).
_PHONE = re.compile(r"(?<!\d)(?:\+?\d[\d\-\x20]{7,}\d)(?!\d)")
_YEARS_EXP = re.compile(
    r"(\d{1,2})\+?\s*(?:years?|yrs?)\s*(?:of\s+)?(?:relevant\s+)?experience",
    re.IGNORECASE,
)
# A LinkedIn profile URL (with or without scheme / www). Captured verbatim.
_LINKEDIN = re.compile(
    r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/(?:in|pub)/[A-Za-z0-9\-_%]+/?",
    re.IGNORECASE,
)
# A "Location: <city>" / "Address: <city>" style line. Deliberately narrow: we only read a
# location the candidate explicitly labelled, never inferred from free text, and it is only
# ever a pre-fill SUGGESTION the candidate edits (location is not a protected attribute, but
# we still keep extraction conservative and verifiable).
_LOCATION = re.compile(
    r"(?im)^\s*(?:location|address|based\s+in|city)\s*[:\-]\s*(.+?)\s*$",
)
# A full name from an explicit "Name: <value>" label (highest confidence, deterministic).
_NAME_LABEL = re.compile(
    r"(?im)^\s*(?:name|full\s*name|candidate\s*name)\s*[:\-]\s*"
    r"([A-Za-z][A-Za-z.'\-]+(?:\s+[A-Za-z][A-Za-z.'\-]+){1,3})\s*$",
)
# A "Skills:" line listing comma/pipe-separated skills, captured verbatim for the candidate
# to edit. Only read from an explicit label so we never guess skills from prose.
_SKILLS_LABEL = re.compile(
    r"(?im)^\s*(?:technical\s+)?(?:key\s+)?skills?(?:\s*&\s*tools)?\s*[:\-]\s*(.+?)\s*$",
)
# A plausible "name heading" as the FIRST non-empty line of a resume (the near-universal
# resume convention: the candidate's name is the first line). Accepts 2-4 capitalised words,
# allows initials/hyphens/apostrophes, and rejects lines containing digits, '@', or typical
# contact/section words so a heading like "Curriculum Vitae" or an address isn't captured.
_NAME_HEADING = re.compile(
    r"^[A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){1,3}$",
)
_NAME_HEADING_STOPWORDS = (
    "resume", "curriculum", "vitae", "cv", "profile", "address", "email", "phone",
    "mobile", "contact", "summary", "objective", "linkedin",
)


def _name_from_first_lines(text: str) -> str | None:
    """Best-effort: the candidate's name is, by near-universal convention, the first real
    line of a resume. Scan the first few non-empty lines for one that looks like a 2-4 word
    proper name and contains no digits / '@' / section words. Returns it or None. This is a
    SUGGESTION only (lower confidence than a labelled 'Name:'), fully editable."""
    lines = [ln.strip() for ln in text.splitlines()]
    checked = 0
    for ln in lines:
        if not ln:
            continue
        checked += 1
        if checked > 5:
            break
        if any(ch.isdigit() for ch in ln) or "@" in ln:
            continue
        low = ln.lower()
        if any(w in low for w in _NAME_HEADING_STOPWORDS):
            continue
        if _NAME_HEADING.match(ln):
            return ln
    return None

# Phrases that look like attempts to steer an automated system. We flag, never act on them.
_INJECTION_MARKERS = (
    "ignore previous instructions",
    "ignore all previous",
    "disregard the above",
    "you are now",
    "system:",
    "assistant:",
    "as an ai",
    "prompt:",
)


@dataclass(frozen=True)
class ExtractedValue:
    field_name: str
    value: str
    confidence: float
    source_span: str


@dataclass
class ResumeExtraction:
    values: list[ExtractedValue] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    text_length: int = 0


def _detect_injection(text: str) -> list[str]:
    lowered = text.lower()
    return [f"possible_injection_marker:{m}" for m in _INJECTION_MARKERS if m in lowered]


def _detect_keyword_stuffing(text: str) -> list[str]:
    flags: list[str] = []
    # Extremely long whitespace-free runs often indicate hidden/obfuscated text.
    if re.search(r"\S{200,}", text):
        flags.append("suspicious_long_token_run")
    tokens = re.findall(r"[A-Za-z]{2,}", text.lower())
    if len(tokens) >= 50:
        most_common = max((tokens.count(t) for t in set(tokens)), default=0)
        if most_common / len(tokens) > 0.3:
            flags.append("suspicious_keyword_repetition")
    return flags


@dataclass(frozen=True)
class SkillMatch:
    """Outcome of searching the resume for one JD skill.

    ``present`` is True when the skill (or one of its declared notation variants) was found.
    ``matched_term`` is the exact term that matched (the JD spelling or an alias), so the
    reason it counts is explainable; it is None when the skill was not found.
    """

    present: bool
    matched_term: str | None


def _term_in_text(lowered_text: str, term: str) -> bool:
    # Word-boundary match on the whole phrase (escaped so "C++", ".NET" are literal).
    pattern = r"(?<![A-Za-z0-9])" + re.escape(term.strip().lower()) + r"(?![A-Za-z0-9])"
    return re.search(pattern, lowered_text) is not None


def match_skills_in_text(text: str, skills: list[str]) -> dict[str, bool]:
    """Deterministically detect which of the given JD skills appear in resume text.

    Matching is a case-insensitive, word-boundary substring search of each skill phrase and
    of its declared notation variants (see skill_alias.py — e.g. "JS" satisfies
    "JavaScript"). It is intentionally literal: it does NOT infer a skill from loosely
    related wording and never treats a merely *related* skill as an equivalent
    (responsible-ai.md); only hand-curated notations of the SAME skill count. A skill that
    is not found is reported as False — this is "not confirmed", NOT proof the candidate
    lacks it, so downstream routes unconfirmed mandatory skills to human review, never a
    rejection.

    Returns a map of {original_skill_name: present}.
    """
    return {name: m.present for name, m in match_skills_detailed(text, skills).items()}


def match_skills_detailed(text: str, skills: list[str]) -> dict[str, SkillMatch]:
    """Like ``match_skills_in_text`` but also reports which term matched (for evidence).

    For each JD skill, every accepted term (the JD spelling plus its declared aliases) is
    searched in order; the first hit wins and its term is recorded as ``matched_term``.
    """
    from app.modules.extraction.skill_alias import expand_skill_terms

    lowered = text.lower()
    result: dict[str, SkillMatch] = {}
    for skill in skills:
        name = skill.strip()
        if not name:
            continue
        matched_term: str | None = None
        for term in expand_skill_terms(name):
            if _term_in_text(lowered, term):
                matched_term = term
                break
        result[name] = SkillMatch(present=matched_term is not None, matched_term=matched_term)
    return result


def extract_resume_fields(text: str) -> ResumeExtraction:
    result = ResumeExtraction(text_length=len(text))
    if not text.strip():
        result.flags.append("empty_text")
        return result

    # Safety flags reduce trust; downstream routes flagged extractions to human review.
    result.flags.extend(_detect_injection(text))
    result.flags.extend(_detect_keyword_stuffing(text))
    confidence_penalty = 0.3 if result.flags else 0.0

    email = _EMAIL.search(text)
    if email:
        result.values.append(
            ExtractedValue("email", email.group(0), max(0.0, 0.9 - confidence_penalty),
                           email.group(0))
        )
    phone = _PHONE.search(text)
    if phone:
        normalised = re.sub(r"[\s\-]", "", phone.group(0))
        result.values.append(
            ExtractedValue("mobile", normalised, max(0.0, 0.7 - confidence_penalty),
                           phone.group(0).strip())
        )
    years = _YEARS_EXP.search(text)
    if years:
        result.values.append(
            ExtractedValue("total_experience_years", years.group(1),
                           max(0.0, 0.6 - confidence_penalty), years.group(0).strip())
        )
    # Full name — prefer an explicit "Name:" label (highest confidence); otherwise fall back
    # to the first-line heading convention (most real resumes put the name first). Both are
    # SUGGESTIONS the candidate edits; the label-based one is more trusted.
    name = _NAME_LABEL.search(text)
    if name:
        result.values.append(
            ExtractedValue("full_name", name.group(1).strip(),
                           max(0.0, 0.8 - confidence_penalty), name.group(0).strip())
        )
    else:
        heading_name = _name_from_first_lines(text)
        if heading_name:
            result.values.append(
                ExtractedValue("full_name", heading_name,
                               max(0.0, 0.6 - confidence_penalty), heading_name)
            )
    # Key skills — only from an explicit "Skills:" line (comma/pipe-separated), verbatim.
    skills = _SKILLS_LABEL.search(text)
    if skills:
        skills_value = skills.group(1).strip()
        # Keep it to a single reasonable line; drop a run-on that is really a paragraph.
        if skills_value and len(skills_value) <= 200:
            result.values.append(
                ExtractedValue("skills", skills_value,
                               max(0.0, 0.6 - confidence_penalty), skills.group(0).strip())
            )
    # Location — only from an explicit "Location:/Address:/City:" label. Keep it short so a
    # mislabelled paragraph isn't captured as a location.
    location = _LOCATION.search(text)
    if location:
        loc_value = location.group(1).strip()
        if loc_value and len(loc_value) <= 80:
            result.values.append(
                ExtractedValue("current_location", loc_value,
                               max(0.0, 0.6 - confidence_penalty), location.group(0).strip())
            )
    # LinkedIn profile URL — captured verbatim (normalised to include a scheme).
    linkedin = _LINKEDIN.search(text)
    if linkedin:
        url = linkedin.group(0).strip().rstrip("/")
        if not url.lower().startswith("http"):
            url = "https://" + url
        result.values.append(
            ExtractedValue("linkedin_url", url, max(0.0, 0.8 - confidence_penalty),
                           linkedin.group(0).strip())
        )
    return result

"""JD field extraction into a structured draft (Req 3.2).

The extractor is deterministic and pattern-based. It only proposes a value when it finds
an explicit, labelled signal in the text (e.g. a "Minimum experience: 3 years" line). It
never infers a qualification from loosely related wording (steering/responsible-ai.md).
Every proposed field carries a confidence and the text span it came from, so a human
reviewer can verify it. Extraction is a SUGGESTION ONLY and requires human approval.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class ProposedField:
    name: str
    value: str
    confidence: float          # 0.0 - 1.0
    source_span: str           # the matched text, for human verification


@dataclass
class JDDraft:
    fields: list[ProposedField] = field(default_factory=list)
    responsibilities: list[str] = field(default_factory=list)
    mandatory_skills: list[str] = field(default_factory=list)
    desirable_skills: list[str] = field(default_factory=list)
    # Separately surfaced for traceability/UI; at the JDVersion level (two skill columns)
    # nice-to-have is merged into desirable, since both are weighted, non-mandatory tiers.
    nice_to_have_skills: list[str] = field(default_factory=list)
    raw_text_length: int = 0
    extraction_notes: list[str] = field(default_factory=list)


# Labelled single-value patterns. Confidence reflects how explicit the label is.
_LABELLED_PATTERNS: tuple[tuple[str, str, float], ...] = (
    ("position_title", r"(?:position|job)\s*title\s*[:\-]\s*(.+)", 0.9),
    ("department", r"department\s*[:\-]\s*(.+)", 0.85),
    ("location", r"location\s*[:\-]\s*(.+)", 0.85),
    ("employment_type", r"employment\s*type\s*[:\-]\s*(.+)", 0.8),
    ("work_mode", r"work\s*mode\s*[:\-]\s*(.+)", 0.8),
    ("notice_period", r"notice\s*period\s*[:\-]\s*(.+)", 0.8),
)

# Minimum years of experience. Tolerant of words BETWEEN "N years" and "experience"
# (e.g. "Minimum 5 years of cloud infrastructure and DevOps engineering experience") and of
# the word order "experience ... N years". Only fires when BOTH a figure+years AND the word
# "experience" are present, so a bare "5 years" elsewhere is not mistaken for a requirement.
_MIN_EXPERIENCE = re.compile(
    r"(?:minimum|min\.?|at\s+least)?\s*(\d{1,2})\+?\s*(?:years?|yrs?)"
    r"(?:[^.\n]*?\bexperience\b)",
    re.IGNORECASE,
)
_OPENINGS = re.compile(
    r"(?:number\s+of\s+openings|openings|vacancies|positions)\s*[:\-]?\s*(\d{1,3})",
    re.IGNORECASE,
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()[:255]


# A collected "skill" line is noise (an experience / qualification / generic requirement
# sentence) rather than an actual skill token, if it matches any of these. Such lines are
# dropped from the skill lists so they never become an exact_skill criterion that no resume
# can match. The scalar experience figure is still captured separately as
# minimum_total_experience_years. Deterministic and purely textual (no inference).
_NON_SKILL_LINE = re.compile(
    r"\b(experience|years?|yrs?|minimum|maximum|at\s+least|notice\s+period|"
    r"salary|ctc|openings?|vacanc|qualification|degree|graduate|bachelor|master)\b",
    re.IGNORECASE,
)


def _collect_list_section(text: str, header_pattern: str, limit: int = 25) -> list[str]:
    """Collect bulleted/line items under a header until a blank line or next header."""
    lines = text.splitlines()
    items: list[str] = []
    capturing = False
    header = re.compile(header_pattern, re.IGNORECASE)
    for line in lines:
        stripped = line.strip()
        if header.search(stripped):
            capturing = True
            continue
        if capturing:
            if not stripped:
                break
            # Stop if we hit another labelled header line.
            if re.match(r"^[A-Z][A-Za-z ]{2,40}:\s*$", stripped):
                break
            cleaned = re.sub(r"^[\-\*\u2022\d\.\)\s]+", "", stripped).strip()
            if cleaned:
                items.append(cleaned[:255])
            if len(items) >= limit:
                break
    return items


# --- Robust, tiered skill extraction for free-form HR job descriptions ------------------
#
# Real JDs are prose: skills are comma/"and"-separated on one line, grouped under tier
# sub-headers ("Must Have:", "Good to Have:", "Nice to Have:"), and often carry a
# parenthetical example, e.g. "Kubernetes (EKS/GKE)". The logic below is still deterministic
# and NON-INFERRING: it only extracts skill tokens that are literally written in the JD. It
# never guesses a skill that isn't there (responsible-ai.md).

# Section header -> which tier the skills under it belong to (until the next header/blank).
_SKILL_SECTION_HEADERS: tuple[tuple[str, str], ...] = (
    (r"must[\s\-]*have", "mandatory"),
    (r"(?:mandatory|required|key)\s*skills?", "mandatory"),
    (r"requirements?", "mandatory"),
    (r"good[\s\-]*to[\s\-]*have", "desirable"),
    (r"(?:desirable|preferred)\s*skills?", "desirable"),
    (r"nice[\s\-]*to[\s\-]*have", "nice_to_have"),
)
_SKILL_HEADER_RE = re.compile(
    r"^\s*(?:" + "|".join(p for p, _ in _SKILL_SECTION_HEADERS) + r")\s*:?\s*$",
    re.IGNORECASE,
)
# Split a free-text requirement line into individual skill tokens.
_SKILL_SPLIT = re.compile(r"\s*(?:,|;|/|\band\b|\bor\b|\|)\s*", re.IGNORECASE)
# A leading "Expertise in", "Experience with", "Proficiency in" etc. before a skill list.
_SKILL_LEADIN = re.compile(
    r"^\s*(?:expertise|experience|proficiency|proficient|skilled|knowledge|hands[\s\-]*on|"
    r"strong|solid|familiar(?:ity)?|working\s+knowledge)\s+"
    r"(?:in|with|of|using)?\s*",
    re.IGNORECASE,
)


def _tier_for_header(line: str) -> str | None:
    for pattern, tier in _SKILL_SECTION_HEADERS:
        # Only treat as a header when the line is essentially JUST the header (a label),
        # not a full sentence that merely mentions the words.
        if re.search(rf"\b{pattern}\b", line, re.IGNORECASE) and (
            _SKILL_HEADER_RE.match(line) or len(line.split()) <= 4
        ):
            return tier
    return None


# Generic trailing qualifier words that describe HOW a skill is used but are not part of the
# skill name. Stripped from the END of a token so "Docker containerization" -> "Docker",
# "Linux administration" -> "Linux", "Helm charts" -> "Helm", "Monitoring stack" ->
# "Monitoring". Purely textual normalisation.
_TRAILING_QUALIFIERS: frozenset[str] = frozenset(
    {"containerization", "administration", "scripting", "automation", "management",
     "stack", "charts", "chart", "engineering", "development", "integration", "iac"}
)
# A lone generic word/phrase that is not a skill on its own (left after stripping
# qualifiers, or leaked from a qualification sentence).
_LONE_GENERIC: frozenset[str] = frozenset(
    {"monitoring", "security", "infrastructure", "secrets", "ci", "cd", "cicd",
     "field", "technical field", "technical", "computer science"}
)


def _normalise_skill_token(token: str) -> str | None:
    """Clean one candidate skill token into a canonical skill name, or None if it is not a
    skill (an experience/qualification fragment, a lone generic word, or empty)."""
    t = token.strip()
    # Strip leading bullet/number and surrounding punctuation / stray parens, trailing dots.
    t = re.sub(r"^[\-\*\u2022\d\.\)\(\s]+", "", t).strip()
    t = t.strip(".()").strip()
    # Strip a lead-in phrase like "Expertise in ...".
    t = _SKILL_LEADIN.sub("", t).strip()
    if not t:
        return None
    # Reject experience/qualification/compensation fragments.
    if _NON_SKILL_LINE.search(t):
        return None
    # Strip trailing generic qualifier words, keeping the head skill.
    words = t.split()
    while len(words) > 1 and words[-1].lower().strip(".") in _TRAILING_QUALIFIERS:
        words.pop()
    t = " ".join(words)
    # A skill token is short; a long remnant is prose, not a skill. Drop lone generics.
    if not t or len(words) > 4 or t.lower() in _LONE_GENERIC:
        return None
    return t[:255]


def _split_skill_line(line: str) -> list[str]:
    """Split one requirement line into individual, normalised skill tokens.

    Parentheticals are FLATTENED into the token stream rather than discarded, so a line like
    "Monitoring stack (Prometheus, Grafana, ELK)" yields the real skills inside the parens,
    while "Kubernetes (EKS/GKE)" yields Kubernetes plus its named variants. Splits on commas,
    slashes, semicolons, pipes, and the words 'and'/'or'.
    """
    # Remove a leading bullet so the lead-in strip works on the first item.
    line = re.sub(r"^[\-\*\u2022\d\.\)\s]+", "", line.strip())
    # Reject the WHOLE line up front if it is clearly a qualification / experience /
    # compensation sentence (e.g. "Bachelor's degree in Computer Science or technical
    # field"). Splitting such a line on "or"/"," would otherwise leak a clean-looking
    # fragment ("technical field") that becomes a bogus skill criterion no resume can match.
    if _NON_SKILL_LINE.search(line):
        return []
    # A single lead-in applies to the whole line ("Expertise in AWS, GCP, Terraform").
    line = _SKILL_LEADIN.sub("", line, count=1)
    # Flatten parentheticals: "X (A, B)" -> "X, A, B" so inner tokens become candidates.
    line = re.sub(r"\s*\(([^)]*)\)", r", \1", line)
    tokens = _SKILL_SPLIT.split(line)
    out: list[str] = []
    for tok in tokens:
        norm = _normalise_skill_token(tok)
        if norm:
            out.append(norm)
    return out


def extract_tiered_skills(text: str) -> dict[str, list[str]]:
    """Extract skills grouped by tier from a free-form JD.

    Returns {"mandatory": [...], "desirable": [...], "nice_to_have": [...]}. Walks the text
    line by line: a recognised tier sub-header switches the active tier; subsequent non-blank
    lines are split into individual skill tokens and added to that tier. De-duplicated
    case-insensitively across tiers (highest tier wins: mandatory > desirable > nice). Purely
    textual and deterministic — only skills literally present are returned.
    """
    result: dict[str, list[str]] = {"mandatory": [], "desirable": [], "nice_to_have": []}
    seen: set[str] = set()
    active: str | None = None

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            active = None  # a blank line ends the current section
            continue
        tier = _tier_for_header(line)
        if tier is not None:
            active = tier
            continue
        if active is None:
            continue
        for skill in _split_skill_line(line):
            key = skill.lower()
            if key not in seen:
                seen.add(key)
                result[active].append(skill)
    return result


def extract_jd_draft(text: str) -> JDDraft:
    draft = JDDraft(raw_text_length=len(text))
    if not text.strip():
        draft.extraction_notes.append("No text could be extracted; manual entry required.")
        return draft

    for name, pattern, confidence in _LABELLED_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = _clean(match.group(1))
            if value:
                draft.fields.append(
                    ProposedField(name=name, value=value, confidence=confidence,
                                  source_span=_clean(match.group(0)))
                )

    exp = _MIN_EXPERIENCE.search(text)
    if exp:
        draft.fields.append(
            ProposedField("minimum_total_experience_years", exp.group(1), 0.75,
                          _clean(exp.group(0)))
        )

    openings = _OPENINGS.search(text)
    if openings:
        draft.fields.append(
            ProposedField("number_of_openings", openings.group(1), 0.7,
                          _clean(openings.group(0)))
        )

    draft.responsibilities = _collect_list_section(
        text, r"(responsibilities|duties|what you.?ll do)"
    )

    # Tiered skill extraction. Handles real HR prose: comma/"and"-separated skills on one
    # line, "Must Have / Good to Have / Nice to Have" sub-headers, lead-ins like "Expertise
    # in ...", and parenthetical examples ("Kubernetes (EKS/GKE)"). Experience/qualification
    # fragments are filtered out (the scalar minimum experience is captured above). The
    # JDVersion carries two skill columns, so nice-to-have is merged into desirable; both are
    # weighted, non-mandatory tiers in the rule generator.
    tiered = extract_tiered_skills(text)
    draft.mandatory_skills = tiered["mandatory"]
    draft.nice_to_have_skills = tiered["nice_to_have"]
    seen_desirable = {s.lower() for s in tiered["desirable"]}
    draft.desirable_skills = tiered["desirable"] + [
        s for s in tiered["nice_to_have"] if s.lower() not in seen_desirable
    ]

    if not draft.fields and not draft.responsibilities:
        draft.extraction_notes.append(
            "No labelled fields detected; the reviewer should enter values manually."
        )
    draft.extraction_notes.append(
        "Extraction is a suggestion only and requires human review before approval."
    )
    return draft

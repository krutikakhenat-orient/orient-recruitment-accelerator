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
# Labelled experience where the figure comes AFTER the label, e.g.
# "Experience: 5 years", "Experience Required: 3+ yrs", "Total Experience - 4 years".
# Complements _MIN_EXPERIENCE (which needs 'experience' to follow the number). The figure is
# taken as the LOWER bound of a range ("3-5 years" -> 3).
_LABELLED_EXPERIENCE = re.compile(
    r"\b(?:total\s+|relevant\s+|work\s+|professional\s+)?experience"
    r"(?:\s+required)?\s*[:\-]\s*(\d{1,2})\+?",
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
# Ordered: more specific tiered headers first, then broader generic skill/technology headers
# that map to the "mandatory" default tier (a plain "Skills:" / "Tech Stack:" list is treated
# as core/required unless a desirable/nice header says otherwise). This broad set is what
# lets the extractor pull skills from an ARBITRARY JD, not only ones using the exact
# "Must Have / Good to Have" wording.
_SKILL_SECTION_HEADERS: tuple[tuple[str, str], ...] = (
    (r"must[\s\-]*have", "mandatory"),
    (r"(?:mandatory|required|key|core|essential|primary)\s*skills?", "mandatory"),
    (r"good[\s\-]*to[\s\-]*have", "desirable"),
    (r"(?:desirable|preferred|secondary|added|additional)\s*skills?", "desirable"),
    (r"nice[\s\-]*to[\s\-]*have", "nice_to_have"),
    # Generic skill/technology section headers (default to the core/mandatory tier). These
    # are deliberately SKILL-specific. We do NOT treat "Requirements", "Qualifications",
    # "Responsibilities", "Key Responsibilities", "About the role" etc. as skill sections:
    # those are prose/logistics and scooping their lines turns whole sentences, headings,
    # dates, locations and salary into bogus skill criteria (the cause of candidates scoring
    # ~5-28% against a garbage denominator). Skills from a prose JD are instead recovered by
    # the known-skill gazetteer scan (see _GAZETTEER) which only matches real skill terms.
    (r"(?:technical|professional)\s*skills?", "mandatory"),
    (r"skills?(?:\s*(?:&|and)\s*(?:competenc|experience)\w*)?", "mandatory"),
    (r"(?:core\s*)?competenc(?:y|ies)", "mandatory"),
    (r"tech(?:nical)?\s*stack", "mandatory"),
    (r"technologies", "mandatory"),
    (r"tools?\s*(?:&|and)\s*technologies", "mandatory"),
)
_SKILL_HEADER_RE = re.compile(
    r"^\s*(?:" + "|".join(p for p, _ in _SKILL_SECTION_HEADERS) + r")\s*:?\s*$",
    re.IGNORECASE,
)
# A header that may carry skills INLINE after a colon, e.g. "Key Skills: Python, SQL, AWS".
# Captures the header label (group 1 = tier-matching text) and the inline remainder (group 2)
# so the skills on the same line as the header are not lost.
_INLINE_HEADER_RE = re.compile(
    r"^\s*(?P<label>(?:"
    + "|".join(p for p, _ in _SKILL_SECTION_HEADERS)
    + r"))\s*:\s*(?P<rest>\S.*)$",
    re.IGNORECASE,
)
# Split a free-text requirement line into individual skill tokens. A slash only separates
# when it has surrounding whitespace ("AWS / Azure") — a tight slash like "TCP/IP", "CI/CD"
# or "I/O" is part of a single compound skill token and must NOT be split.
_SKILL_SPLIT = re.compile(r"\s*(?:,|;|\s/\s|\band\b|\bor\b|\|)\s*", re.IGNORECASE)
# A leading "Expertise in", "Experience with", "Proficiency in" etc. before a skill list.
_SKILL_LEADIN = re.compile(
    r"^\s*(?:expertise|experience|proficiency|proficient|skilled|knowledge|hands[\s\-]*on|"
    r"strong|solid|familiar(?:ity)?|working\s+knowledge)\s+"
    r"(?:in|with|of|using)?\s*",
    re.IGNORECASE,
)


def _tier_for_label(label: str) -> str | None:
    """Resolve a header label string (e.g. 'Key Skills', 'Tech Stack') to its tier, or None.

    The FIRST matching pattern wins, so the ordering in _SKILL_SECTION_HEADERS (specific
    must/good/nice first, then generic skill/tech headers) determines precedence.
    """
    for pattern, tier in _SKILL_SECTION_HEADERS:
        if re.search(rf"\b{pattern}\b", label, re.IGNORECASE):
            return tier
    return None


def _tier_for_header(line: str) -> str | None:
    """Return the tier for a line that is ESSENTIALLY just a section header (a short label),
    not a full sentence that merely mentions the words. Used for header-only lines where the
    skills appear on the following lines."""
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
# Action verbs that START a responsibility sentence ("Configure and troubleshoot...",
# "Monitor and analyze...", "Provide L2 operational support"). A token beginning with one of
# these is a duty, not a skill, so it is rejected. This stops a prose "Responsibilities"
# section (or any sentence) from being chopped into bogus skill criteria.
_RESPONSIBILITY_VERBS: frozenset[str] = frozenset(
    {"provide", "configure", "troubleshoot", "maintain", "manage", "monitor", "analyze",
     "analyse", "handle", "support", "perform", "coordinate", "ensure", "implement",
     "deploy", "install", "review", "document", "escalate", "resolve", "respond",
     "assist", "collaborate", "lead", "develop", "design", "build", "create", "define",
     "execute", "operate", "administer", "optimize", "optimise", "validate", "conduct",
     "prepare", "deliver", "work", "participate", "drive", "own", "track", "report"}
)
# A token that is really a section HEADING (e.g. "JOB DESCRIPTION", "KEY RESPONSIBILITIES",
# "WALK-IN DETAILS") — all-caps multi-word labels are headings, not skills.
_HEADING_WORDS: frozenset[str] = frozenset(
    {"job", "description", "responsibilities", "responsibility", "details", "detail",
     "overview", "summary", "role", "about", "company", "position", "walk-in", "walkin",
     "drive", "venue", "date", "timing", "timings", "location", "eligibility", "benefits",
     "compensation", "salary", "notes", "note", "process", "requirements", "requirement",
     "qualifications", "qualification", "objective", "profile"}
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
    words = t.split()
    first = words[0].lower().strip(".,")
    # Reject a RESPONSIBILITY sentence/fragment that starts with an action verb
    # ("Configure", "Monitor and analyze security events", "Provide L2 support"). These are
    # duties, not skills.
    if first in _RESPONSIBILITY_VERBS:
        return None
    # Reject a section HEADING ("JOB DESCRIPTION", "KEY RESPONSIBILITIES", "WALK-IN DETAILS").
    # Any token whose words are all heading words is a label, not a skill.
    if all(w.lower().strip(".,:") in _HEADING_WORDS for w in words):
        return None
    # Strip trailing generic qualifier words, keeping the head skill.
    while len(words) > 1 and words[-1].lower().strip(".") in _TRAILING_QUALIFIERS:
        words.pop()
    t = " ".join(words)
    # A skill token is short; a long remnant is prose, not a skill. Drop lone generics.
    # Tightened from 4 to 3 words: genuine skill names are rarely longer, and the looser
    # limit let multi-word duty fragments through.
    if not t or len(words) > 3 or t.lower() in _LONE_GENERIC:
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


# --- Known-skill gazetteer -------------------------------------------------------------
#
# Many real JDs are pure prose with no clean "Skills:" list (just a title, responsibilities
# and logistics). Chopping such prose into tokens produces garbage criteria. Instead we scan
# the JD for a curated set of KNOWN skill terms and keep the ones literally present. This is
# deterministic and non-inferring: a term is only added if it appears verbatim (word-
# boundary, case-insensitive) in the JD. The gazetteer spans the role families this product
# serves (networking/security, infra/cloud, programming, data, IT support). Extend as new
# role families are onboarded. Multi-word entries are matched as phrases.
_GAZETTEER: tuple[str, ...] = (
    # Networking & security
    "Firewall", "Firewalls", "VPN", "IPSec", "SSL VPN", "IDS", "IPS", "NAT", "Routing",
    "Switching", "TCP/IP", "DNS", "DHCP", "BGP", "OSPF", "VLAN", "LAN", "WAN", "LAN/WAN",
    "SD-WAN", "Proxy", "SIEM", "SOC", "Wireshark", "Palo Alto", "Fortinet", "FortiGate",
    "Checkpoint", "Cisco", "Cisco ASA", "Juniper", "Sophos", "Zscaler", "Active Directory",
    "Load Balancer", "F5", "Network Security", "Endpoint Security", "Penetration Testing",
    "Vulnerability Assessment", "Nmap", "Nessus", "Burp Suite", "Access Control",
    # Cloud & infra
    "AWS", "Azure", "GCP", "Google Cloud", "Docker", "Kubernetes", "Terraform", "Ansible",
    "Jenkins", "Linux", "Windows Server", "VMware", "Hyper-V", "Nginx", "Apache", "Bash",
    "PowerShell", "Git", "CI/CD", "Prometheus", "Grafana", "ELK", "Helm",
    # Programming & data
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", ".NET", "Go", "Golang",
    "Rust", "PHP", "Ruby", "Node.js", "React", "Angular", "Vue", "Spring Boot", "Django",
    "Flask", "FastAPI", "SQL", "MySQL", "PostgreSQL", "Oracle", "MongoDB", "Redis", "Kafka",
    "REST", "REST APIs", "GraphQL", "Power BI", "Tableau", "Excel",
    # IT support / desktop
    "Troubleshooting", "Hardware", "Software Installation", "Operating Systems", "Windows",
    "macOS", "Desktop Support", "Laptop", "Remote Desktop", "Ticketing", "ServiceNow",
    "MS Office", "Office 365", "Outlook", "Printers", "Antivirus", "Patch Management",
    "Asset Management", "ITIL", "Incident Management", "SLA", "Email Configuration",
    # Customer support / BPO / voice process
    "Customer Support", "Customer Service", "Inbound Calls", "Outbound Calls",
    "Call Handling", "Telecalling", "Tele Sales", "CRM", "Query Resolution",
    "Complaint Handling", "Escalation", "Chat Support", "Email Support", "Voice Process",
    "Non-Voice Process", "BPO", "Typing", "Data Entry", "Cold Calling", "Lead Generation",
    # Languages commonly required for support roles
    "English", "Hindi", "Marathi", "Tamil", "Telugu", "Kannada", "Bengali", "Gujarati",
    # Office / data tools
    "Excel", "Power BI", "Tableau",
    # Soft/role skills commonly screened
    "Communication", "Technical Support", "Documentation", "Interpersonal Skills",
)
# Precompiled phrase patterns (longest first so "LAN/WAN" wins over "LAN"/"WAN").
_GAZETTEER_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (
        term,
        re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.IGNORECASE),
    )
    for term in sorted(_GAZETTEER, key=len, reverse=True)
)


def scan_known_skills(text: str) -> list[str]:
    """Return the curated gazetteer skills that literally appear in the JD text, in gazetteer
    order, de-duplicated case-insensitively. Deterministic, non-inferring: a skill is only
    returned when it appears verbatim (word-boundary). This recovers real skills from a prose
    JD that has no explicit skills section, without turning sentences into criteria.

    Redundant near-duplicates are collapsed: a singular/plural pair keeps one form
    ("Firewall"/"Firewalls" -> "Firewall"), and a token wholly contained in a longer matched
    compound is dropped ("LAN" and "WAN" are dropped when "LAN/WAN" also matched) so the
    generated criteria are not double-counted."""
    present = {term for term, pat in _GAZETTEER_PATTERNS if pat.search(text)}

    # Collapse singular/plural: if both "X" and "Xs" matched, keep only "X".
    def _plural_dup(term: str) -> bool:
        return term.endswith("s") and term[:-1] in present

    kept: list[str] = []
    seen: set[str] = set()
    for term in _GAZETTEER:
        if term not in present:
            continue
        key = term.lower()
        if key in seen or _plural_dup(term):
            continue
        # Drop a short token that is a whole word inside a longer matched compound
        # (e.g. "LAN"/"WAN" subsumed by "LAN/WAN"), avoiding double-weighting.
        subsumed = any(
            other != term
            and other in present
            and re.search(rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])", other)
            for other in present
        )
        if subsumed:
            continue
        seen.add(key)
        kept.append(term)
    return kept


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

    def _add(tier: str, line_text: str) -> None:
        for skill in _split_skill_line(line_text):
            key = skill.lower()
            if key not in seen:
                seen.add(key)
                result[tier].append(skill)

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            active = None  # a blank line ends the current section
            continue

        # Case A: a header with skills INLINE on the same line ("Key Skills: Python, SQL").
        # Capture the inline skills AND switch the active tier so following lines continue it.
        inline = _INLINE_HEADER_RE.match(line)
        if inline is not None:
            tier = _tier_for_label(inline.group("label"))
            if tier is not None:
                active = tier
                _add(tier, inline.group("rest"))
                continue

        # Case B: a header-only line ("Must Have:"). Switch the active tier; skills follow.
        tier = _tier_for_header(line)
        if tier is not None:
            active = tier
            continue

        # Case C: a body line under the active section.
        if active is None:
            continue
        _add(active, line)
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

    exp = _MIN_EXPERIENCE.search(text) or _LABELLED_EXPERIENCE.search(text)
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

    # Known-skill gazetteer scan. Prose JDs (a title + responsibilities + logistics, no clean
    # "Skills:" section) yield few or no tiered skills; the gazetteer recovers the REAL skill
    # terms that literally appear in the text. We merge gazetteer hits into the MANDATORY tier
    # only when they are not already captured under an explicit tier (so an explicit
    # Good-to-Have skill keeps its tier). This keeps scoring meaningful for arbitrary JDs
    # without turning prose sentences into criteria.
    gazetteer = scan_known_skills(text)
    already = {s.lower() for s in tiered["mandatory"] + tiered["desirable"]
               + tiered["nice_to_have"]}
    for skill in gazetteer:
        if skill.lower() not in already:
            tiered["mandatory"].append(skill)
            already.add(skill.lower())

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

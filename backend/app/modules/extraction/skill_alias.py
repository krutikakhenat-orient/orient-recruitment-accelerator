"""Deterministic skill-alias taxonomy (responsible-ai.md).

Skill matching is intentionally LITERAL — it never infers a skill from loosely related
wording and never treats a *related* skill as an exact equivalent. This module is the one
place where known *spelling / notation variants of the SAME skill* are declared explicitly.

The distinction is deliberate and binding:
  - ALLOWED here: notation variants that denote the identical skill, e.g. "JavaScript" and
    "JS", "PostgreSQL" and "Postgres", "Node.js" and "NodeJS". These are the same skill
    written differently.
  - NEVER here: adjacent or "related" skills, e.g. Java != JavaScript, React != Angular,
    MySQL != PostgreSQL. Scoring one as the other would be inference, which is prohibited.

Because the taxonomy is a curated, hand-maintained lookup table (data, not code, and no
fuzzy/semantic logic), matching stays fully deterministic and reproducible: the same JD
skill + the same resume text + the same TAXONOMY_VERSION always yield the same result.

A match found only via an alias is still recorded; downstream it is treated exactly like a
direct match. A skill that is not found under its canonical name OR any declared alias is
"not confirmed" (never proof of absence) and routes a mandatory skill to human review.
"""

from __future__ import annotations

import re

# Bump when the alias table below changes so screening runs remain explainable: a stored
# run can report which taxonomy version produced its skill matches.
TAXONOMY_VERSION = "skill-alias-v1"

# canonical display name -> tuple of alternative notations that mean the SAME skill.
# Keys and alias values are matched case-insensitively; keep entries lower-cased here.
_ALIASES: dict[str, tuple[str, ...]] = {
    "javascript": ("js", "ecmascript"),
    "typescript": ("ts",),
    "node.js": ("nodejs", "node js", "node"),
    "postgresql": ("postgres", "psql"),
    "python": ("py",),
    "c#": ("c sharp", "csharp"),
    "c++": ("cpp", "cplusplus"),
    ".net": ("dotnet", "dot net"),
    "kubernetes": ("k8s",),
    "amazon web services": ("aws",),
    "google cloud platform": ("gcp",),
    "microsoft azure": ("azure",),
    "continuous integration": ("ci",),
    "continuous delivery": ("cd",),
    "ci/cd": ("cicd", "ci cd"),
    "react": ("react.js", "reactjs"),
    "vue": ("vue.js", "vuejs"),
    "angular": ("angular.js", "angularjs"),
    "structured query language": ("sql",),
    "golang": ("go",),
    "machine learning": ("ml",),
    "natural language processing": ("nlp",),
    "representational state transfer": ("rest", "restful"),
}


def aliases_for(skill: str) -> tuple[str, ...]:
    """Return the declared notation variants for a skill (empty when none are known).

    The lookup is bidirectional: given either the canonical name OR one of its aliases, it
    returns the OTHER notations for the same skill (plus the canonical name when an alias
    was supplied), so a JD may list the skill under any known notation. Matching is always
    anchored on the skill as written in the JD; aliases only ADD extra accepted spellings
    and never substitute a different, merely-related skill.
    """
    key = skill.strip().lower()
    if not key:
        return ()
    if key in _ALIASES:
        return _ALIASES[key]
    # Supplied value may itself be an alias: return the canonical name + sibling aliases.
    for canonical, variants in _ALIASES.items():
        if key in variants:
            return (canonical, *tuple(v for v in variants if v != key))
    return ()


# A trailing version suffix on a skill name — the SAME skill written with a release number,
# e.g. "Python 3.12", "PostgreSQL 14", "Java 17", "Python 3.x", "postgres 14.2". Stripping
# it yields the base skill. This is a deterministic notation normalisation (same skill,
# version annotation removed), NOT inference: "Python 3.12" and "Python" are the identical
# skill, whereas unrelated skills are never conflated (responsible-ai.md).
_VERSION_SUFFIX = re.compile(
    r"\s+v?\d+(?:\.\d+)*(?:\.x)?\s*$",  # " 3", " 3.12", " 14.2", " 3.x", " v2"
    re.IGNORECASE,
)


def strip_version_suffix(skill: str) -> str:
    """Remove a trailing release/version annotation from a skill name.

    "Python 3.12" -> "Python"; "PostgreSQL 14" -> "PostgreSQL"; "Python 3.x" -> "Python".
    A name with no version suffix is returned unchanged. Deterministic and purely textual.
    """
    stripped = _VERSION_SUFFIX.sub("", skill.strip())
    # Guard against reducing the whole token away (e.g. a skill that is only digits).
    return stripped if stripped else skill.strip()


# Descriptor words that commonly wrap a core skill in JD prose but are not part of the
# skill's name. Stripped so a verbose JD skill like "PostgreSQL database optimization" also
# matches a resume that just says "PostgreSQL", and "Redis caching" matches "Redis". Purely
# textual: the core term is still a word that literally appears in the JD skill phrase, so
# this is normalisation, not inference.
_DESCRIPTOR_WORDS: frozenset[str] = frozenset(
    {
        # structural / optimisation nouns
        "database", "optimization", "optimisation", "caching", "cache", "standards",
        "standard", "specification", "specifications", "specs", "containerization",
        "containerisation", "administration", "scripting", "management", "charts", "chart",
        "stack", "designing", "design", "development", "engineering", "integration",
        "automation", "queues", "queue", "iac", "logs", "log", "systems", "system",
        "tools", "tooling", "frameworks", "framework", "libraries", "library", "compliance",
        "build", "pipeline", "pipelines", "practices", "patterns", "principles", "concepts",
        "fundamentals", "ecosystem", "environments", "environment", "platform", "platforms",
        # lead-in / proficiency qualifiers
        "expertise", "expert", "proficiency", "proficient", "skilled", "knowledge",
        "hands-on", "handson", "strong", "solid", "advanced", "deep", "extensive",
        "excellent", "good", "familiar", "familiarity", "working", "modern",
        "exposure", "understanding", "experience", "experienced", "demonstrated",
        # generic adjectives/nouns that wrap a skill
        "web", "frontend", "front-end", "backend", "back-end", "fullstack", "full-stack",
        "cloud", "data", "quality", "security",
        # stopwords / connectives
        "with", "in", "of", "and", "or", "using", "the", "a", "an", "to", "for", "on",
    }
)


def core_skill_terms(skill: str) -> list[str]:
    """Reduce a verbose JD skill phrase to its core skill token(s) by removing descriptor
    words. "PostgreSQL database optimization" -> ["PostgreSQL"]; "REST specifications" ->
    ["REST"]; "hash-chained audit logs" -> ["hash-chained", "audit"]. Returns the kept words
    (each a term literally present in the phrase). Empty when nothing substantive remains."""
    words = re.findall(r"[A-Za-z0-9#.+/\-]+", skill)
    kept = [w for w in words if w.lower().strip(".") not in _DESCRIPTOR_WORDS]
    # Drop pure version tokens like "3.10+" or "3.x".
    kept = [w for w in kept if not re.fullmatch(r"v?\d+(?:\.\d+)*(?:\.x)?\+?", w, re.IGNORECASE)]
    return kept


def expand_skill_terms(skill: str) -> list[str]:
    """All accepted search terms for a skill: the skill as written, its version-stripped
    base, its core token(s) with descriptor words removed, and declared aliases of each.

    De-duplicated case-insensitively, preserving order (the JD's own spelling first). Used
    by the matcher so a resume saying "JS" satisfies a JD skill "JavaScript", "Python 3.12"
    is satisfied by "Python", and a verbose JD skill like "PostgreSQL database optimization"
    is satisfied by a resume that names the core tech "PostgreSQL". Still literal: every
    accepted term is a word that appears in the JD skill or a declared notation variant — a
    merely *related* skill such as "Java" never satisfies "JavaScript".
    """
    terms: list[str] = []
    seen: set[str] = set()

    def _add(term: str) -> None:
        norm = term.strip()
        key = norm.lower()
        if norm and key not in seen:
            seen.add(key)
            terms.append(norm)

    base = strip_version_suffix(skill)
    # Order: exact JD spelling, its aliases, the version-stripped base + aliases.
    _add(skill)
    for a in aliases_for(skill):
        _add(a)
    if base.lower() != skill.strip().lower():
        _add(base)
        for a in aliases_for(base):
            _add(a)

    # Core token(s) with descriptor words removed — but ONLY when the phrase is multi-word
    # (a single-word skill is already its own core, and we must not weaken it). When exactly
    # one substantive token remains, use it as a search term + its aliases. When several
    # remain (e.g. "hash-chained audit logs"), the phrase is genuinely multi-word; we still
    # add the individual kept tokens so a resume mentioning any of them can match.
    if len(skill.split()) > 1:
        core = core_skill_terms(skill)
        if len(core) == 1:
            _add(core[0])
            for a in aliases_for(core[0]):
                _add(a)
    return terms

"""JD extraction: experience/qualification lines must not pollute the skill lists (Req 3.2).

Extraction is a deterministic suggestion for human review. The skill lists it proposes must
contain actual skills, not experience/qualification sentences collected under a generic
"Requirements:" header — otherwise those become exact_skill criteria that no resume can
match, forcing every candidate to a 0 skill score. The minimum experience is still captured
as its own scalar field.
"""

from __future__ import annotations

from app.modules.extraction.jd_extractor import extract_jd_draft

JD = (
    "Position Title: AI Engineer\n"
    "Department: Engineering\n"
    "Minimum 1 year experience in machine learning\n"
    "\n"
    "Requirements:\n"
    "- Minimum Total Experience: 1 year\n"
    "- Python\n"
    "- FastAPI\n"
    "- Bachelor's degree in Computer Science\n"
    "\n"
    "Good to have:\n"
    "- Docker\n"
    "- 3+ years experience with Kubernetes\n"
)

# A realistic, prose-style HR JD: comma/"and"-separated skills on one line, tier
# sub-headers, lead-ins ("Expertise in ..."), and parenthetical examples.
DEVOPS_JD = (
    "Job Description: DevOps & Cloud Systems Engineer\n"
    "Position Overview\n"
    "We are looking for a DevOps & Cloud Engineer to manage our infrastructure.\n"
    "Key Requirements\n"
    "Must Have:\n"
    "Minimum 5 years of cloud infrastructure and DevOps engineering experience.\n"
    "Expertise in AWS or GCP, Terraform IaC, and Kubernetes (EKS/GKE).\n"
    "Good to Have:\n"
    "Docker containerization, Helm charts, and CI/CD automation (GitHub Actions / GitLab CI).\n"
    "Linux administration, Bash/Python scripting.\n"
    "Nice to Have:\n"
    "Monitoring stack (Prometheus, Grafana, ELK).\n"
    "Infrastructure security & secrets management (HashiCorp Vault).\n"
)


def test_prose_jd_extracts_tiered_comma_separated_skills() -> None:
    from app.modules.extraction.jd_extractor import extract_tiered_skills

    tiered = extract_tiered_skills(DEVOPS_JD)
    mand = {s.lower() for s in tiered["mandatory"]}
    des = {s.lower() for s in tiered["desirable"]}
    nice = {s.lower() for s in tiered["nice_to_have"]}

    # Must-have skills are extracted from the comma/"and"/"or" sentence (lead-in stripped,
    # trailing qualifier "IaC" removed), and the experience sentence under the same header is
    # filtered out.
    assert {"aws", "gcp", "terraform", "kubernetes"} <= mand
    assert not any("experience" in s or "years" in s for s in mand)

    # Good-to-have skills are tokenised from prose lines (head skill kept).
    assert "docker" in des
    assert "helm" in des

    # Nice-to-have monitoring/security tools are captured from inside the parentheticals.
    assert {"prometheus", "grafana", "elk"} <= nice
    assert any("vault" in s for s in nice)


def test_qualification_sentence_does_not_leak_a_bogus_skill() -> None:
    # "Bachelor's degree in Computer Science or technical field" is a qualification sentence;
    # splitting on "or" must NOT leak "technical field" as a skill criterion.
    from app.modules.extraction.jd_extractor import extract_tiered_skills

    jd = (
        "Must Have:\n"
        "Minimum 5 years of Python experience.\n"
        "Strong hands-on expertise with Python 3.10+ and FastAPI or Django.\n"
        "Bachelor's degree in Computer Science or technical field.\n"
    )
    tiered = extract_tiered_skills(jd)
    mand = {s.lower() for s in tiered["mandatory"]}
    assert "technical field" not in mand
    assert all("degree" not in s and "field" not in s for s in mand)
    # Real skills still extracted.
    assert "fastapi" in mand
    assert "django" in mand


def test_prose_jd_captures_minimum_experience_scalar() -> None:
    draft = extract_jd_draft(DEVOPS_JD)
    by_name = {f.name: f.value for f in draft.fields}
    assert by_name.get("minimum_total_experience_years") == "5"


def test_prose_jd_merges_nice_into_desirable_for_two_column_model() -> None:
    draft = extract_jd_draft(DEVOPS_JD)
    des_lower = {s.lower() for s in draft.desirable_skills}
    # Nice-to-have folds into desirable at the JDVersion level (two skill columns).
    assert {"prometheus", "grafana"} <= des_lower
    # Must-have stays separate.
    assert all(s.lower() not in des_lower for s in ("aws", "gcp"))


def test_experience_and_qualification_lines_are_not_skills() -> None:
    draft = extract_jd_draft(JD)
    assert "Python" in draft.mandatory_skills
    assert "FastAPI" in draft.mandatory_skills
    # Experience / qualification sentences are filtered out of the skill list.
    assert "Minimum Total Experience: 1 year" not in draft.mandatory_skills
    assert all("degree" not in s.lower() for s in draft.mandatory_skills)
    assert all("experience" not in s.lower() for s in draft.mandatory_skills)


def test_desirable_skills_filtered_too() -> None:
    draft = extract_jd_draft(JD)
    assert "Docker" in draft.desirable_skills
    assert all("experience" not in s.lower() for s in draft.desirable_skills)


def test_minimum_experience_still_captured_as_scalar() -> None:
    draft = extract_jd_draft(JD)
    by_name = {f.name: f.value for f in draft.fields}
    assert by_name.get("minimum_total_experience_years") == "1"

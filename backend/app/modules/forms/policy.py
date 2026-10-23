"""Form policy: prohibited fields and baseline field definitions (Req 4.1).

Prohibited keys must never appear on an application form because they could introduce
protected/medical/highly-personal characteristics into screening (steering/privacy.md,
responsible-ai.md). The policy rejects any attempt to add them. Compensation fields are
only permitted when the form version explicitly enables compensation.
"""

from __future__ import annotations

from app.core.errors import ValidationError
from app.modules.forms.models import FieldClass

# Keys (and obvious synonyms) that must never be collected on the application form.
PROHIBITED_FIELD_KEYS: frozenset[str] = frozenset(
    {
        "date_of_birth", "dob", "age", "gender", "sex", "marital_status",
        "medical_condition", "disability", "religion", "caste", "race", "ethnicity",
        "sexual_orientation", "photograph", "photo", "vaccination", "covid_vaccination",
        "hobbies", "family", "family_information",
    }
)


def assert_field_allowed(key: str, field_class: str, *, compensation_enabled: bool) -> None:
    normalised = key.strip().lower()
    if normalised in PROHIBITED_FIELD_KEYS:
        raise ValidationError(
            f"Field '{key}' is prohibited and must not be collected on the application form"
        )
    if field_class == FieldClass.COMPENSATION.value and not compensation_enabled:
        raise ValidationError(
            "Compensation fields require compensation to be explicitly enabled for the campaign"
        )


# Baseline fields generated for a new form draft. Compensation fields are added only when
# the campaign enables compensation.
# Cities offered for the candidate's current location (a dropdown, not free text).
LOCATION_OPTIONS: tuple[str, ...] = (
    "Mumbai", "Pune", "Bangalore", "Turbhe", "Delhi", "Ahmedabad",
)

# How the candidate heard about the opening (from the interview application form).
SOURCE_OPTIONS: tuple[str, ...] = (
    "Company website", "Job Portal", "Social Media", "Reference",
)

# Column definitions for the repeating "Education history" table. Each candidate row holds
# these sub-fields. None of these are protected/medical/personal attributes, so the
# repeating table is allowed on the form (privacy.md).
EDUCATION_ITEM_FIELDS: tuple[dict[str, object], ...] = (
    {"key": "qualification", "label": "Qualification / degree", "field_type": "text",
     "required": True},
    {"key": "institution", "label": "Institution / university", "field_type": "text",
     "required": True},
    {"key": "year_of_completion", "label": "Year of completion", "field_type": "number",
     "required": False},
    {"key": "grade", "label": "Grade / percentage", "field_type": "text", "required": False},
)

# Column definitions for the repeating "Work history" table.
WORK_ITEM_FIELDS: tuple[dict[str, object], ...] = (
    {"key": "employer", "label": "Employer", "field_type": "text", "required": True},
    {"key": "designation", "label": "Designation", "field_type": "text", "required": True},
    {"key": "from_year", "label": "From (year)", "field_type": "number", "required": False},
    {"key": "to_year", "label": "To (year, or blank if current)", "field_type": "number",
     "required": False},
    {"key": "responsibilities", "label": "Key responsibilities", "field_type": "textarea",
     "required": False},
)

# Baseline fields generated for a new form draft, mapped from the Interview Application
# Form. NOTE: fields that could introduce protected / medical / highly-personal
# characteristics (date of birth, gender, marital status, medical history, vaccination
# status, hobbies) are DELIBERATELY omitted — they are prohibited on the application form
# (privacy.md, responsible-ai.md) and would be rejected by assert_field_allowed anyway.
# Compensation (salary) fields are added only when the campaign enables compensation.
BASELINE_FIELDS: tuple[dict[str, object], ...] = (
    # NOTE: "position applied for" is intentionally NOT collected on the form — the candidate
    # already chooses the role (campaign) they are applying to, so a separate free-text
    # position field is redundant. The campaign's position title is the authoritative value
    # and is filled in automatically on submit (see applications.service.submit_application).
    {"key": "full_name", "label": "Candidate name", "field_class": FieldClass.CORE_IDENTITY.value,
     "field_type": "text", "required": True},
    {"key": "email", "label": "E-mail address", "field_class": FieldClass.CORE_IDENTITY.value,
     "field_type": "email", "required": True},
    {"key": "mobile", "label": "Mobile number", "field_class": FieldClass.CORE_IDENTITY.value,
     "field_type": "text", "required": True},
    {"key": "current_location", "label": "Current location",
     "field_class": FieldClass.CORE_IDENTITY.value, "field_type": "select",
     "required": True, "options": list(LOCATION_OPTIONS)},
    {"key": "total_experience_years", "label": "Total experience (years)",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value, "field_type": "number",
     "required": True},
    {"key": "current_employer", "label": "Current organization",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value, "field_type": "text",
     "required": False},
    {"key": "current_designation", "label": "Current designation",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value, "field_type": "text",
     "required": False},
    {"key": "notice_period", "label": "Notice period",
     "field_class": FieldClass.AVAILABILITY.value, "field_type": "text", "required": True},
    {"key": "skills", "label": "Key skills", "field_class": FieldClass.SKILLS_EXPERIENCE.value,
     "field_type": "text", "required": True},
    {"key": "strengths", "label": "Strengths",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value, "field_type": "textarea",
     "required": False},
    {"key": "weaknesses", "label": "Weaknesses",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value, "field_type": "textarea",
     "required": False},
    {"key": "education", "label": "Highest qualification",
     "field_class": FieldClass.EDUCATION_CERTIFICATION.value, "field_type": "text",
     "required": True},
    {"key": "certifications", "label": "Professional certification (if any)",
     "field_class": FieldClass.EDUCATION_CERTIFICATION.value, "field_type": "text",
     "required": False},
    {"key": "education_history", "label": "Education history",
     "field_class": FieldClass.EDUCATION_CERTIFICATION.value,
     "field_type": "repeating_group", "required": False,
     "item_fields": list(EDUCATION_ITEM_FIELDS)},
    {"key": "work_history", "label": "Work history",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value,
     "field_type": "repeating_group", "required": False,
     "item_fields": list(WORK_ITEM_FIELDS)},
    {"key": "career_gap", "label": "Career gap, if any",
     "field_class": FieldClass.SKILLS_EXPERIENCE.value, "field_type": "textarea",
     "required": False},
    {"key": "interviewed_last_six_months", "label": "Interviewed by us in the last six months?",
     "field_class": FieldClass.ELIGIBILITY.value, "field_type": "boolean", "required": False},
    {"key": "heard_about_opening", "label": "How did you learn about the opening?",
     "field_class": FieldClass.ELIGIBILITY.value, "field_type": "select",
     "required": False, "options": list(SOURCE_OPTIONS)},
    {"key": "reference_name", "label": "Reference (if any)",
     "field_class": FieldClass.ELIGIBILITY.value, "field_type": "text", "required": False},
    {"key": "resume", "label": "Resume", "field_class": FieldClass.RESUME_ATTACHMENT.value,
     "field_type": "file", "required": True},
    {"key": "candidate_declaration", "label": "Candidate declaration",
     "field_class": FieldClass.CONSENT_DECLARATION.value, "field_type": "boolean",
     "required": True},
    {"key": "privacy_consent", "label": "Privacy consent",
     "field_class": FieldClass.CONSENT_DECLARATION.value, "field_type": "boolean",
     "required": True},
    {"key": "talent_pool_consent", "label": "Join talent pool (optional)",
     "field_class": FieldClass.CONSENT_DECLARATION.value, "field_type": "boolean",
     "required": False},
)

COMPENSATION_FIELDS: tuple[dict[str, object], ...] = (
    {"key": "current_ctc", "label": "Current salary (CTC)",
     "field_class": FieldClass.COMPENSATION.value, "field_type": "number", "required": False},
    {"key": "current_in_hand", "label": "Current in-hand salary",
     "field_class": FieldClass.COMPENSATION.value, "field_type": "number", "required": False},
    {"key": "expected_ctc", "label": "Expected salary (CTC)",
     "field_class": FieldClass.COMPENSATION.value, "field_type": "number", "required": False},
)

"""Built-in message templates and the safe renderer.

Placeholders use ``{{name}}``. Only the placeholders a template declares are filled; any
other key a caller passes is ignored. Context keys that could leak internal assessment
data (scores, ranks, recommendations, notes) are rejected outright (AC-15, G8).

HR can override any template; an override becomes a new versioned row. The built-ins below
are used until then and are reported as version 0.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.errors import ValidationError

FORBIDDEN_CONTEXT_KEYS: frozenset[str] = frozenset(
    {"score", "rank", "recommendation", "notes", "internal_notes", "rating", "verdict"}
)

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


@dataclass(frozen=True)
class BuiltInTemplate:
    key: str
    label: str
    audience: str  # "candidate" | "joiner" | "staff" | "interviewer"
    description: str
    subject: str
    body: str
    placeholders: tuple[str, ...]


BUILT_IN_TEMPLATES: tuple[BuiltInTemplate, ...] = (
    BuiltInTemplate(
        key="interview_confirm_request",
        label="Interview: please confirm",
        audience="candidate",
        description="Sent with the personal confirmation link after an interview is arranged.",
        subject="Please confirm your interview for {{role}}",
        body=(
            "Hello {{candidate_name}},\n\n"
            "You are invited to an interview for the {{role}} role. "
            "Please confirm that you can attend, or ask for a different time, using this "
            "personal link:\n{{link}}\n\n"
            "The link works once and expires, so please reply soon.\n\nThank you,\nHR team"
        ),
        placeholders=("candidate_name", "role", "link"),
    ),
    BuiltInTemplate(
        key="interview_reminder",
        label="Interview: reminder",
        audience="candidate",
        description="A friendly reminder before the interview date.",
        subject="Reminder: your interview for {{role}}",
        body=(
            "Hello {{candidate_name}},\n\n"
            "This is a reminder about your interview for {{role}}.\n"
            "When: {{when}}\nWhere: {{where}}\n\n"
            "If anything changes, please let us know as soon as you can.\n\nThank you,\nHR team"
        ),
        placeholders=("candidate_name", "role", "when", "where"),
    ),
    BuiltInTemplate(
        key="interviewer_confirmation_notice",
        label="Interviewer: candidate replied",
        audience="interviewer",
        description="Tells the interviewer how the candidate replied to the invitation.",
        subject="Candidate reply: {{response}} for {{role}}",
        body=(
            "Hello,\n\n{{candidate_name}} has replied to the interview invitation for "
            "{{role}}: {{response}}.\nSlot: {{when}}\n\nThank you."
        ),
        placeholders=("candidate_name", "role", "response", "when"),
    ),
    BuiltInTemplate(
        key="offer_issued",
        label="Offer: issued",
        audience="candidate",
        description="Tells the candidate their offer is ready.",
        subject="Your offer for {{role}}",
        body=(
            "Hello {{candidate_name}},\n\n"
            "We are pleased to share your offer for the {{role}} role. "
            "Please reply by {{respond_by}}.\n\nThank you,\nHR team"
        ),
        placeholders=("candidate_name", "role", "respond_by"),
    ),
    BuiltInTemplate(
        key="offer_followup",
        label="Offer: follow-up",
        audience="candidate",
        description="A gentle reminder while an offer has not been answered.",
        subject="Following up on your offer for {{role}}",
        body=(
            "Hello {{candidate_name}},\n\n"
            "We are following up on the offer for {{role}}. "
            "Please let us know your decision by {{respond_by}}.\n\nThank you,\nHR team"
        ),
        placeholders=("candidate_name", "role", "respond_by"),
    ),
    BuiltInTemplate(
        key="document_request",
        label="Joining: documents needed",
        audience="joiner",
        description="Shares the list of documents needed before joining.",
        subject="Documents needed for your joining",
        body=(
            "Hello {{candidate_name}},\n\n"
            "Welcome aboard. To complete your joining as {{role}}, please send us:\n"
            "{{documents}}\n\nThank you,\nHR team"
        ),
        placeholders=("candidate_name", "role", "documents"),
    ),
    BuiltInTemplate(
        key="document_reminder",
        label="Joining: document reminder",
        audience="joiner",
        description="Reminds the joiner of the documents still outstanding.",
        subject="Reminder: documents still needed",
        body=(
            "Hello {{candidate_name}},\n\n"
            "We are still waiting for:\n{{documents}}\n\n"
            "Please send them when you can.\n\nThank you,\nHR team"
        ),
        placeholders=("candidate_name", "documents"),
    ),
    BuiltInTemplate(
        key="prejoining_info",
        label="Joining: before day one",
        audience="joiner",
        description="Reporting manager, department and what to expect on day one.",
        subject="Getting ready for your first day",
        body=(
            "Hello {{candidate_name}},\n\n"
            "Your joining date is {{joining_date}}.\n"
            "Role: {{role}}\nDepartment: {{department}}\n"
            "Reporting manager: {{reporting_manager}}\nLocation: {{work_location}}\n\n"
            "What to expect: {{role_expectations}}\n\nSee you soon,\nHR team"
        ),
        placeholders=(
            "candidate_name", "role", "joining_date", "department",
            "reporting_manager", "work_location", "role_expectations",
        ),
    ),
    BuiltInTemplate(
        key="welcome_joiner",
        label="Joining: welcome",
        audience="joiner",
        description="A welcome message on the joining date.",
        subject="Welcome to the team",
        body=(
            "Hello {{candidate_name}},\n\nWelcome! We are glad you are joining the "
            "{{department}} team as {{role}} today.\n\nHR team"
        ),
        placeholders=("candidate_name", "role", "department"),
    ),
    BuiltInTemplate(
        key="joiner_announcement",
        label="Joining: team announcement",
        audience="staff",
        description="Announces the new joiner to the team. HR chooses the recipients.",
        subject="Please welcome {{candidate_name}}",
        body=(
            "Hello team,\n\nPlease join us in welcoming {{candidate_name}}, who joins "
            "{{department}} as {{role}} on {{joining_date}}.\n\nHR team"
        ),
        placeholders=("candidate_name", "role", "department", "joining_date"),
    ),
    BuiltInTemplate(
        key="sla_reminder",
        label="SLA: at risk",
        audience="staff",
        description="Warns the recruiter that shortlisting decisions are getting close to due.",
        subject="Shortlisting due soon: {{campaign_name}}",
        body=(
            "Hello,\n\n{{count}} application(s) in {{campaign_name}} are close to the "
            "{{window_hours}}-hour shortlisting target. Please review them.\n\nThank you."
        ),
        placeholders=("campaign_name", "count", "window_hours"),
    ),
    BuiltInTemplate(
        key="sla_escalation",
        label="SLA: overdue",
        audience="staff",
        description="Escalates applications that passed the shortlisting target.",
        subject="Shortlisting overdue: {{campaign_name}}",
        body=(
            "Hello,\n\n{{count}} application(s) in {{campaign_name}} are past the "
            "{{window_hours}}-hour shortlisting target and need attention.\n\nThank you."
        ),
        placeholders=("campaign_name", "count", "window_hours"),
    ),
)

_BY_KEY = {t.key: t for t in BUILT_IN_TEMPLATES}


def built_in(key: str) -> BuiltInTemplate:
    template = _BY_KEY.get(key)
    if template is None:
        raise ValidationError(f"Unknown message template: {key}")
    return template


def assert_safe_context(context: dict[str, str]) -> None:
    leaked = FORBIDDEN_CONTEXT_KEYS.intersection(k.lower() for k in context)
    if leaked:
        raise ValidationError(
            "Messages must not include internal assessment data: " + ", ".join(sorted(leaked))
        )


def placeholders_in(text: str) -> set[str]:
    return set(_PLACEHOLDER.findall(text))


def render(text: str, allowed: tuple[str, ...], context: dict[str, str]) -> str:
    assert_safe_context(context)

    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in allowed:
            return ""
        return str(context.get(name, ""))

    return _PLACEHOLDER.sub(_sub, text)


def single_line(text: str) -> str:
    """Subjects must be one line (prevents header injection)."""
    return re.sub(r"[\r\n]+", " ", text).strip()[:255]

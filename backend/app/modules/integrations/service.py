"""Integration registry: a plain-language list of every external connection and its state.

States:
  live           - connected and delivering
  simulated      - demo mode, nothing really leaves the system
  not_configured - a placeholder; the feature works locally but the connection is missing
  planned        - not built yet; a feasibility study comes first
"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.config import Settings
from app.modules.notifications import providers as notification_providers
from app.modules.notifications.models import Channel


class IntegrationRead(BaseModel):
    key: str
    name: str
    purpose: str
    state: str
    message: str
    needs: list[str]
    used_by: list[str]


def list_integrations(settings: Settings) -> list[IntegrationRead]:
    email = notification_providers.channel_state(Channel.EMAIL.value, settings)
    whatsapp = notification_providers.channel_state(Channel.WHATSAPP.value, settings)

    if settings.ai_interview_enabled:
        ai_state = "simulated" if settings.ai_interview_agent_mode == "fake" else "live"
        ai_message = "Switched on. The interview agent service must also be running."
    else:
        ai_state = "not_configured"
        ai_message = "Switched off. The hiring process works fully without it."

    return [
        IntegrationRead(
            key="email", name="Email", purpose="Send candidate, joiner and staff emails.",
            state=email["state"], message=email["message"],
            needs=[
                "Set ORA_NOTIFICATION_EMAIL_MODE to smtp (or simulate for a demo).",
                "Set ORA_NOTIFICATION_SMTP_HOST and ORA_NOTIFICATION_SMTP_PORT "
                "(the MailHog dev sandbox works locally).",
                "Later: Microsoft 365 / Outlook provider (to be confirmed with IT).",
            ],
            used_by=["Interview confirmation", "Offers", "Joining documents", "SLA reminders"],
        ),
        IntegrationRead(
            key="whatsapp", name="WhatsApp", purpose="Reminders and document chasers.",
            state=whatsapp["state"], message=whatsapp["message"],
            needs=[
                "A WhatsApp Business provider account.",
                "Approved message templates and candidate opt-in.",
                "A provider adapter (placeholder today).",
            ],
            used_by=["Interview reminders", "Document reminders"],
        ),
        IntegrationRead(
            key="calendar", name="Calendar (Microsoft 365)",
            purpose="Read interviewer availability and create interview events.",
            state="not_configured",
            message="Not connected. Interview slots are planned by hand; suggestions use the "
            "slots you already created.",
            needs=["IT approval for calendar access.", "A calendar provider adapter."],
            used_by=["Interview scheduling"],
        ),
        IntegrationRead(
            key="ai_interview", name="AI pre-screening interview",
            purpose="A short voice interview before the technical round (advisory only).",
            state=ai_state, message=ai_message,
            needs=["Set ORA_AI_INTERVIEW_ENABLED and the interview agent settings."],
            used_by=["Candidate journey: pre-screening"],
        ),
        IntegrationRead(
            key="llm", name="AI assistant adapter",
            purpose="Optional AI for summaries. Always advisory, never a decision.",
            state="not_configured",
            message="Off. Summaries and answers use fixed, rule-based logic.",
            needs=["A model provider and a data-protection review before real use."],
            used_by=["Feedback summary", "HR assistant"],
        ),
        IntegrationRead(
            key="zinghr", name="ZingHR", purpose="Create employee records after joining.",
            state="planned",
            message="Placeholder. HR can preview the record that would be sent; nothing is sent.",
            needs=["ZingHR API access, scope and a sandbox (feasibility study first)."],
            used_by=["Offers & onboarding: ZingHR preview"],
        ),
        IntegrationRead(
            key="sourcing", name="Naukri / NOCR sourcing",
            purpose="Bring in candidates from job platforms.",
            state="planned",
            message="Placeholder. Needs a feasibility study (official API, terms, consent).",
            needs=["Commercial terms and API access.", "Consent and lawful-basis review."],
            used_by=["Applications"],
        ),
        IntegrationRead(
            key="avatar_video", name="AI avatar induction",
            purpose="A presenter-led induction video.",
            state="planned",
            message="Placeholder. Today the induction uses a recorded video.",
            needs=["Vendor evaluation, consent and accessibility review."],
            used_by=["Employee induction"],
        ),
    ]

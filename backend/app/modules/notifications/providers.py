"""Message providers behind one interface.

Nothing here ever reports ``sent`` unless a real provider accepted the message. The
default is ``UnconfiguredProvider`` (nothing leaves the system). ``SimulatedProvider`` is
for local demos and reports ``simulated``. ``SmtpEmailProvider`` delivers through an SMTP
server such as the MailHog dev sandbox.

WhatsApp has NO live provider yet. A WhatsApp Business account and approved message
templates are required first; until then only ``unconfigured`` / ``simulate`` modes exist.
"""

from __future__ import annotations

import re
import smtplib
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol
from urllib.parse import quote

from app.core.config import Settings
from app.modules.notifications.models import Channel, DeliveryStatus


@dataclass(frozen=True)
class SendResult:
    status: str
    provider_response_id: str | None = None
    failure_reason: str | None = None


class MessageProvider(Protocol):
    name: str

    def send(self, *, to: str, subject: str, body: str) -> SendResult: ...


class UnconfiguredProvider:
    name = "unconfigured"

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        return SendResult(status=DeliveryStatus.UNCONFIGURED.value)


class SimulatedProvider:
    name = "simulate"

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        return SendResult(
            status=DeliveryStatus.SIMULATED.value,
            provider_response_id=f"simulated-{uuid.uuid4().hex[:12]}",
        )


class SmtpEmailProvider:
    name = "smtp"

    def __init__(self, host: str, port: int, sender: str) -> None:
        self._host = host
        self._port = port
        self._sender = sender

    def send(self, *, to: str, subject: str, body: str) -> SendResult:
        message = EmailMessage()
        message["From"] = self._sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as smtp:
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException):
            # Never echo server details to the user; the operator can read the logs.
            return SendResult(
                status=DeliveryStatus.FAILED.value,
                failure_reason="The mail server could not be reached or rejected the message.",
            )
        return SendResult(
            status=DeliveryStatus.SENT.value, provider_response_id=f"smtp-{uuid.uuid4().hex[:12]}"
        )


def provider_for(channel: str, settings: Settings) -> MessageProvider:
    if channel == Channel.EMAIL.value:
        mode = settings.notification_email_mode
        if mode == "smtp":
            return SmtpEmailProvider(
                settings.notification_smtp_host,
                settings.notification_smtp_port,
                settings.notification_sender_address,
            )
        if mode == "simulate":
            return SimulatedProvider()
        return UnconfiguredProvider()
    if channel == Channel.WHATSAPP.value:
        # No live WhatsApp provider exists yet (placeholder).
        if settings.notification_whatsapp_mode == "simulate":
            return SimulatedProvider()
        return UnconfiguredProvider()
    return UnconfiguredProvider()


def channel_state(channel: str, settings: Settings) -> dict[str, str]:
    """Plain-language state of a channel for the Integrations / status screens."""
    if channel == Channel.EMAIL.value:
        mode = settings.notification_email_mode
        if mode == "smtp":
            return {
                "mode": mode,
                "state": "live",
                "message": "Email is delivered through the configured mail server.",
            }
        if mode == "simulate":
            return {
                "mode": mode,
                "state": "simulated",
                "message": "Demo mode: emails are recorded but not actually delivered.",
            }
        return {
            "mode": "unconfigured",
            "state": "not_configured",
            "message": "No email provider is connected. Messages are recorded with a "
            "ready-to-send link so you can send them by hand.",
        }
    mode = settings.notification_whatsapp_mode
    if mode == "simulate":
        return {
            "mode": mode,
            "state": "simulated",
            "message": "Demo mode: WhatsApp messages are recorded but not delivered.",
        }
    return {
        "mode": "unconfigured",
        "state": "not_configured",
        "message": "WhatsApp is a placeholder. It needs a WhatsApp Business provider account "
        "and approved message templates before it can send.",
    }


def manual_link(channel: str, to: str, subject: str, body: str) -> str:
    """A link a person can click to send the message by hand when no provider is set up."""
    if channel == Channel.WHATSAPP.value:
        digits = re.sub(r"\D", "", to)
        return f"https://wa.me/{digits}?text={quote(body)[:1800]}"
    return f"mailto:{quote(to)}?subject={quote(subject)}&body={quote(body)[:1800]}"

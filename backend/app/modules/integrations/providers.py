"""Placeholder adapters for systems that are not connected yet.

Each adapter has a stable interface so a real implementation can replace the placeholder
without changing callers. None of them make network calls, and none assume any vendor API
behaviour that has not been confirmed (see docs/BRD.md, Phase 0 feasibility studies).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PushResult:
    state: str  # "not_configured" for the placeholder
    message: str
    payload_preview: dict[str, Any] = field(default_factory=dict)


class HrmsProvider(Protocol):
    """An HR system of record (ZingHR is the intended first integration)."""

    name: str

    def build_employee_record(self, data: dict[str, Any]) -> dict[str, Any]: ...

    def push_employee_record(self, record: dict[str, Any]) -> PushResult: ...


class PlaceholderHrmsProvider:
    """Builds a preview of what WOULD be sent. Nothing is sent: ZingHR API access, scope and
    a sandbox have not been confirmed yet."""

    name = "zinghr (placeholder)"

    def build_employee_record(self, data: dict[str, Any]) -> dict[str, Any]:
        # Only the fields needed for an employee record (data minimisation). No documents,
        # no identity numbers, no assessment data.
        return {
            "full_name": data.get("full_name"),
            "work_email": None,
            "designation": data.get("designation"),
            "department": data.get("department"),
            "reporting_manager": data.get("reporting_manager"),
            "date_of_joining": data.get("date_of_joining"),
            "work_location": data.get("work_location"),
            "employee_code": None,
        }

    def push_employee_record(self, record: dict[str, Any]) -> PushResult:
        return PushResult(
            state="not_configured",
            message=(
                "ZingHR is not connected. This is a preview of the record that would be "
                "sent after HR confirms it. Nothing has been sent."
            ),
            payload_preview=record,
        )


class SourcingProvider(Protocol):
    """A candidate-sourcing platform (for example Naukri / NOCR), via official APIs only."""

    name: str

    def search(self, query: dict[str, Any]) -> PushResult: ...


class PlaceholderSourcingProvider:
    name = "sourcing (placeholder)"

    def search(self, query: dict[str, Any]) -> PushResult:
        return PushResult(
            state="not_configured",
            message=(
                "No sourcing platform is connected. A feasibility study (official API, "
                "terms, consent) comes first. Scraping is not used."
            ),
        )


class CalendarProvider(Protocol):
    name: str

    def free_busy(self, user_email: str) -> PushResult: ...


class PlaceholderCalendarProvider:
    name = "calendar (placeholder)"

    def free_busy(self, user_email: str) -> PushResult:
        return PushResult(
            state="not_configured",
            message="No calendar is connected. Enter interviewer availability by hand for now.",
        )


def hrms_provider() -> HrmsProvider:
    return PlaceholderHrmsProvider()


def sourcing_provider() -> SourcingProvider:
    return PlaceholderSourcingProvider()


def calendar_provider() -> CalendarProvider:
    return PlaceholderCalendarProvider()

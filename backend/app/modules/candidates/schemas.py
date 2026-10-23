"""Candidate Pydantic schemas.

Contact PII (email, mobile, LinkedIn) is MASKED by default on the standard candidate read.
Unmasked contact details are only ever returned by the dedicated contact endpoint, which
requires the ``candidate.view_pii`` permission and writes an audit event for every access
(security.md: object-level, least-privilege access to candidate content).
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


def mask_email(email: str | None) -> str | None:
    """Mask an email as ``a***@d***.com`` style, preserving only enough to be recognisable.

    Deterministic and lossy — it never reveals the full local-part or domain.
    """
    if not email or "@" not in email:
        return None if not email else "***"
    local, _, domain = email.partition("@")
    local_masked = (local[0] + "***") if local else "***"
    # Keep the TLD but mask the domain label.
    if "." in domain:
        label, _, rest = domain.partition(".")
        domain_masked = (label[0] + "***." + rest) if label else "***." + rest
    else:
        domain_masked = "***"
    return f"{local_masked}@{domain_masked}"


def mask_phone(phone: str | None) -> str | None:
    """Mask a phone number, revealing only the last two digits."""
    if not phone:
        return None
    digits = [c for c in phone if c.isdigit()]
    if len(digits) < 2:
        return "***"
    return "••• ••• " + "".join(digits[-2:])


def mask_linkedin(linkedin: str | None) -> str | None:
    """Indicate presence of a LinkedIn profile without revealing the handle."""
    if not linkedin:
        return None
    return "linkedin.com/in/•••"


class CandidateRead(BaseModel):
    """Standard candidate read — contact PII is masked. Safe for list/detail views."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organisation_id: uuid.UUID
    full_name: str
    email_masked: str | None
    mobile_masked: str | None
    linkedin_masked: str | None
    in_talent_pool: bool
    version: int

    @classmethod
    def from_candidate(cls, candidate: object) -> CandidateRead:
        return cls(
            id=candidate.id,  # type: ignore[attr-defined]
            organisation_id=candidate.organisation_id,  # type: ignore[attr-defined]
            full_name=candidate.full_name,  # type: ignore[attr-defined]
            email_masked=mask_email(candidate.email),  # type: ignore[attr-defined]
            mobile_masked=mask_phone(candidate.mobile),  # type: ignore[attr-defined]
            linkedin_masked=mask_linkedin(getattr(candidate, "linkedin", None)),
            in_talent_pool=candidate.in_talent_pool,  # type: ignore[attr-defined]
            version=candidate.version,  # type: ignore[attr-defined]
        )


class CandidateContactRead(BaseModel):
    """Unmasked contact details. Returned ONLY by the audited view_pii endpoint."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    email: str
    mobile: str | None
    linkedin: str | None

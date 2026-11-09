"""Document consistency checks.

This is NOT authenticity or forgery detection. It compares what a person typed in (the name
shown on a document, its expiry date) with what is already on record and with the joining
date, and flags gaps for HR. A flag never changes a status by itself: HR decides.

``DocumentVerifier`` is the seam for a future AI/OCR extractor. Until one is connected the
rule-based checker below is the only implementation and the screen says so plainly.
"""

from __future__ import annotations

import datetime as dt
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

from app.modules.onboarding.models import DocStatus, FlagKind

AI_VERIFICATION_NOTE = (
    "AI reading of the uploaded files is not connected yet (placeholder). These checks compare "
    "the details HR entered with the candidate record and the joining date."
)


@dataclass(frozen=True)
class DocumentView:
    id: uuid.UUID
    name: str
    required: bool
    status: str
    name_on_document: str | None
    expiry_date: dt.date | None


@dataclass(frozen=True)
class FlagSpec:
    kind: str
    document_id: uuid.UUID | None
    message: str


class DocumentVerifier(Protocol):
    def check(
        self,
        documents: list[DocumentView],
        *,
        candidate_name: str,
        joining_date: dt.date | None,
        today: dt.date,
    ) -> list[FlagSpec]: ...


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z]+", name.lower()) if t}


def names_consistent(candidate_name: str, document_name: str) -> bool:
    """True when one name's words are contained in the other (middle names are tolerated)."""
    a, b = _tokens(candidate_name), _tokens(document_name)
    if not a or not b:
        return False
    return a <= b or b <= a


class RuleBasedVerifier:
    def check(
        self,
        documents: list[DocumentView],
        *,
        candidate_name: str,
        joining_date: dt.date | None,
        today: dt.date,
    ) -> list[FlagSpec]:
        flags: list[FlagSpec] = []
        received = {DocStatus.SUBMITTED.value, DocStatus.ACCEPTED.value}
        for doc in documents:
            if doc.status == DocStatus.WAIVED.value:
                continue
            if doc.status not in received:
                if doc.required:
                    flags.append(
                        FlagSpec(FlagKind.MISSING.value, doc.id,
                                 f"{doc.name} has not been received yet.")
                    )
                continue
            if not doc.name_on_document:
                flags.append(
                    FlagSpec(FlagKind.NEEDS_DETAILS.value, doc.id,
                             f"{doc.name}: the name shown on the document was not entered, "
                             "so it could not be compared.")
                )
            elif not names_consistent(candidate_name, doc.name_on_document):
                flags.append(
                    FlagSpec(FlagKind.MISMATCH.value, doc.id,
                             f"{doc.name}: the name on the document does not match the "
                             "candidate name on record.")
                )
            if doc.expiry_date is not None:
                limit = joining_date or today
                if doc.expiry_date < limit:
                    when = "before the joining date" if joining_date else "already"
                    flags.append(
                        FlagSpec(FlagKind.EXPIRED.value, doc.id,
                                 f"{doc.name} expires {when} ({doc.expiry_date.isoformat()}).")
                    )
        return flags


def default_verifier() -> DocumentVerifier:
    return RuleBasedVerifier()

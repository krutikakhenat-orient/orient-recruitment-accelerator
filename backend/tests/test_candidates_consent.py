"""Tests for candidate resolution, consent, duplicate detection (Req 5.2, 5.4, 11.3)."""

from __future__ import annotations

from app.modules.candidates import service
from app.modules.candidates.models import (
    Candidate,
    CandidateDuplicateLink,
    ConsentPurpose,
    ConsentRecord,
    ConsentState,
)
from tests.factories import make_org


def test_resolve_creates_then_reuses_candidate(db_session) -> None:
    org = make_org(db_session)
    r1 = service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="Jane Synthetic",
        email="Jane.Synthetic@example.com", mobile="123",
    )
    assert r1.created is True
    r2 = service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="Jane Synthetic",
        email="jane.synthetic@example.com", mobile="123",
    )
    assert r2.created is False
    assert r2.candidate.id == r1.candidate.id
    assert db_session.query(Candidate).count() == 1


def test_same_email_different_name_flags_duplicate(db_session) -> None:
    org = make_org(db_session)
    service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="Jane Synthetic",
        email="dup@example.com", mobile=None,
    )
    r = service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="Different Person",
        email="dup@example.com", mobile=None,
    )
    assert r.duplicate_flagged is True
    assert db_session.query(CandidateDuplicateLink).count() == 1


def test_talent_pool_consent_is_separate_and_withdrawable(db_session) -> None:
    org = make_org(db_session)
    cand = service.resolve_candidate(
        db_session, organisation_id=org.id, full_name="Jane", email="j@example.com",
        mobile=None,
    ).candidate

    # Application consent does not enrol in talent pool.
    service.record_consent(db_session, organisation_id=org.id, candidate_id=cand.id,
                           purpose=ConsentPurpose.APPLICATION, notice_version="v1")
    assert cand.in_talent_pool is False

    # Separate talent-pool opt-in enrols.
    service.record_consent(db_session, organisation_id=org.id, candidate_id=cand.id,
                           purpose=ConsentPurpose.TALENT_POOL, notice_version="v1")
    assert cand.in_talent_pool is True

    # Withdrawal (AC-16).
    service.withdraw_talent_pool_consent(db_session, organisation_id=org.id,
                                         candidate_id=cand.id)
    assert cand.in_talent_pool is False
    withdrawn = (
        db_session.query(ConsentRecord)
        .filter_by(candidate_id=cand.id, purpose=ConsentPurpose.TALENT_POOL.value)
        .first()
    )
    assert withdrawn.state == ConsentState.WITHDRAWN.value
    assert withdrawn.withdrawn_at is not None

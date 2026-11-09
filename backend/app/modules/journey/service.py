"""Candidate journey read model.

Reads the existing records for ONE application (state, screening run, AI pre-screening
session, interview invitation, assessment, offer, joining case) and turns them into a single
ordered list of stages with a status and a plain-language "what happens next". It changes
nothing and decides nothing: it only reports where the person is.

Like the reporting module, this is a cross-module READ model, so it reads the other modules'
tables directly instead of calling each service.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ai_interviews.models import AiInterviewSession, AiInterviewStatus
from app.modules.applications.models import Application
from app.modules.applications.states import ApplicationState
from app.modules.assessments.models import Assessment
from app.modules.campaigns.models import Campaign
from app.modules.candidates import service as candidate_service
from app.modules.interviews.models import AttendanceStatus, InterviewInvitation, InvitationStatus
from app.modules.journey.schemas import JourneyRead, JourneyStage
from app.modules.onboarding.models import (
    CaseStatus,
    DocStatus,
    Offer,
    OfferStatus,
    OnboardingCase,
    OnboardingDocument,
)
from app.modules.screening.models import ScreeningRun

_S = ApplicationState
_ORDER: dict[str, int] = {
    _S.SUBMITTED.value: 0,
    _S.DOCUMENTS_PROCESSING.value: 1,
    _S.EXTRACTION_REVIEW.value: 2,
    _S.SCREENED.value: 3,
    _S.MANUAL_REVIEW.value: 3,
    _S.ADDITIONAL_INFO_REQUESTED.value: 3,
    _S.INTERVIEW_RECOMMENDED.value: 4,
    _S.INTERVIEW_SCHEDULED.value: 5,
    _S.CHECKED_IN.value: 6,
    _S.ATTENDED.value: 6,
    _S.NO_SHOW.value: 6,
    _S.ASSESSED.value: 7,
    _S.CHECKED_OUT.value: 7,
    _S.SELECTED.value: 8,
    _S.REJECTED.value: 8,
    _S.HOLD.value: 8,
    _S.WAITLISTED.value: 8,
    _S.WITHDRAWN.value: 8,
}
_DECISION_LABEL = {
    _S.SELECTED.value: "Selected",
    _S.REJECTED.value: "Not selected",
    _S.HOLD.value: "On hold",
    _S.WAITLISTED.value: "On the waitlist",
    _S.WITHDRAWN.value: "Candidate withdrew",
}
_CLOSED_STATES = {_S.REJECTED.value, _S.WITHDRAWN.value}

_NEXT = {
    "resume_checked": "The system is reading the resume and form.",
    "screened": "Run screening so the approved rules can be applied.",
    "hr_review": "A recruiter should review this candidate and choose the next step.",
    "interview_invited": (
        "Approve an interview invitation and send the candidate a confirmation link."
    ),
    "interview_confirmed": "Waiting for the candidate to confirm the interview.",
    "interview_done": "Hold the interview. The panel then records an assessment.",
    "decision": "A hiring manager should record the decision.",
    "offer": "Prepare, approve and send the offer.",
    "documents": "Collect and check the joining documents.",
    "joining": "Confirm the joining details and welcome the new joiner.",
}


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _stage(
    key: str, label: str, description: str, owner: str, status: str, *,
    optional: bool = False, detail: str | None = None, at: dt.datetime | None = None,
) -> JourneyStage:
    return JourneyStage(
        key=key, label=label, description=description, owner=owner, status=status,
        optional=optional, detail=detail, at=_aware(at),
    )


def build_journey(db: Session, application: Application) -> JourneyRead:
    org = application.organisation_id
    state = application.state
    order = _ORDER.get(state, 0)
    candidate = candidate_service.get_candidate(
        db, organisation_id=org, candidate_id=application.candidate_id
    )
    campaign = db.get(Campaign, application.campaign_id)

    run = db.execute(
        select(ScreeningRun)
        .where(ScreeningRun.application_id == application.id)
        .order_by(ScreeningRun.started_at.desc())
        .limit(1)
    ).scalars().first()
    ai = db.execute(
        select(AiInterviewSession)
        .where(AiInterviewSession.application_id == application.id)
        .order_by(AiInterviewSession.created_at.desc())
        .limit(1)
    ).scalars().first()
    invitation = db.execute(
        select(InterviewInvitation)
        .where(InterviewInvitation.application_id == application.id)
        .order_by(InterviewInvitation.created_at.desc())
        .limit(1)
    ).scalars().first()
    assessment_count = len(
        db.execute(select(Assessment.id).where(Assessment.application_id == application.id)).all()
    )
    offer = db.execute(
        select(Offer).where(Offer.application_id == application.id)
        .order_by(Offer.created_at.desc()).limit(1)
    ).scalars().first()
    case = db.execute(
        select(OnboardingCase).where(OnboardingCase.application_id == application.id)
    ).scalars().first()

    closed = state in _CLOSED_STATES
    decided = state in _DECISION_LABEL
    selected = state == _S.SELECTED.value
    stages: list[JourneyStage] = []

    stages.append(_stage(
        "applied", "Applied", "The candidate submitted the application form and resume.",
        "Candidate", "done", at=application.created_at,
    ))

    resume_done = order >= 2
    stages.append(_stage(
        "resume_checked", "Resume checked",
        "The system reads the resume and form. Staff can verify what it found.",
        "System", "done" if resume_done else "current",
    ))

    screened_done = run is not None or order >= 3
    stages.append(_stage(
        "screened", "Screened",
        "Approved rules are applied. The result is a recommendation, never a decision.",
        "System",
        "done" if screened_done else ("current" if resume_done else "upcoming"),
        at=run.started_at if run else None,
    ))

    if state in {_S.MANUAL_REVIEW.value, _S.ADDITIONAL_INFO_REQUESTED.value}:
        review_status = "blocked" if state == _S.ADDITIONAL_INFO_REQUESTED.value else "current"
        review_detail = (
            "Waiting for more information from the candidate."
            if state == _S.ADDITIONAL_INFO_REQUESTED.value
            else "A person needs to look at this application."
        )
    elif state == _S.SCREENED.value:
        review_status, review_detail = "current", "Choose the next step for this candidate."
    elif order >= 4:
        review_status, review_detail = "done", None
    else:
        review_status, review_detail = "upcoming", None
    stages.append(_stage(
        "hr_review", "HR review",
        "A recruiter looks at anything unclear or borderline and chooses what happens next.",
        "Recruiter", review_status, detail=review_detail,
    ))

    if ai is None:
        ai_status, ai_detail = "skipped", "Not used for this candidate."
    elif ai.status == AiInterviewStatus.COMPLETED.value:
        ai_status, ai_detail = "done", "The advisory summary is ready for the recruiter."
    elif ai.status in {AiInterviewStatus.APPROVED.value, AiInterviewStatus.IN_PROGRESS.value}:
        ai_status, ai_detail = "current", "Waiting for the candidate to take the short interview."
    elif ai.status in {AiInterviewStatus.REVOKED.value, AiInterviewStatus.EXPIRED.value}:
        ai_status, ai_detail = "skipped", "The link was withdrawn or expired."
    else:
        ai_status, ai_detail = "upcoming", "Questions are waiting for a recruiter to approve them."
    stages.append(_stage(
        "pre_screening", "Short AI interview",
        "An optional short voice interview before the technical round. Advisory only.",
        "Candidate", ai_status, optional=True, detail=ai_detail,
        at=ai.completed_at if ai else None,
    ))

    if invitation is not None or order >= 5:
        invited_status = "done"
    elif state == _S.INTERVIEW_RECOMMENDED.value:
        invited_status = "current"
    else:
        invited_status = "upcoming"
    stages.append(_stage(
        "interview_invited", "Interview invited",
        "HR approves an invitation and shares a personal confirmation link.",
        "Recruiter admin", invited_status, at=invitation.invited_at if invitation else None,
    ))

    confirm_detail = None
    if invitation is None:
        confirm_status = "upcoming"
    elif invitation.status == InvitationStatus.CONFIRMED.value:
        confirm_status = "done"
    elif invitation.status == InvitationStatus.DECLINED.value:
        confirm_status, confirm_detail = "blocked", "The candidate said they can't attend."
    elif invitation.status == InvitationStatus.RESCHEDULE_REQUESTED.value:
        confirm_status, confirm_detail = "blocked", "The candidate asked for a different time."
    else:
        confirm_status = "current"
        confirm_detail = "Waiting for the candidate's reply."
    stages.append(_stage(
        "interview_confirmed", "Interview confirmed",
        "The candidate confirms the time and the interviewer is told automatically.",
        "Candidate", confirm_status, detail=confirm_detail,
        at=invitation.confirmed_at if invitation else None,
    ))

    interview_over = (
        order >= 7 or assessment_count > 0
        or (invitation is not None and invitation.attendance == AttendanceStatus.CHECKED_OUT.value)
    )
    if interview_over:
        done_status, done_detail = "done", None
    elif state == _S.CHECKED_IN.value or (
        invitation is not None and invitation.attendance == AttendanceStatus.CHECKED_IN.value
    ):
        done_status, done_detail = "current", "The interview is in progress."
    elif state == _S.INTERVIEW_SCHEDULED.value:
        done_status, done_detail = "current", "Scheduled. Waiting for the interview day."
    else:
        done_status, done_detail = "upcoming", None
    stages.append(_stage(
        "interview_done", "Interview held",
        "The panel checks the candidate in and records an assessment.",
        "Interviewer", done_status, detail=done_detail,
        at=invitation.checked_out_at if invitation else None,
    ))

    if decided:
        decision_status, decision_detail = "done", _DECISION_LABEL[state]
    elif order >= 7:
        decision_status, decision_detail = "current", "Waiting for the hiring decision."
    else:
        decision_status, decision_detail = "upcoming", None
    stages.append(_stage(
        "decision", "Decision",
        "A hiring manager records the outcome. People make this decision, not the system.",
        "Recruiter admin", decision_status, detail=decision_detail,
    ))

    # Stages after the decision only apply to a selected candidate.
    after_label = {
        "offer": ("Offer", "An offer is prepared, approved and sent.", "Recruiter admin"),
        "documents": (
            "Joining documents", "Joining documents are collected and checked.",
            "Candidate and HR",
        ),
        "joining": ("Joining", "Joining details are confirmed and the person joins.", "HR"),
    }
    if not selected:
        skipped_detail = (
            "Not applicable." if closed else "Starts only if the candidate is selected."
        )
        after_status = "skipped" if closed else "upcoming"
        for key, (label, desc, owner) in after_label.items():
            stages.append(_stage(key, label, desc, owner, after_status, detail=skipped_detail))
    else:
        # Offer
        if offer is None:
            o_status, o_detail = "current", "No offer has been prepared yet."
        elif offer.status == OfferStatus.ACCEPTED.value:
            o_status, o_detail = "done", "Offer accepted."
        elif offer.status in {
            OfferStatus.DECLINED.value, OfferStatus.EXPIRED.value, OfferStatus.WITHDRAWN.value
        }:
            o_status, o_detail = "blocked", f"Offer {offer.status}."
        else:
            o_status, o_detail = "current", f"Offer {offer.status}."
        stages.append(_stage(
            "offer", after_label["offer"][0], after_label["offer"][1], after_label["offer"][2],
            o_status, detail=o_detail, at=offer.issued_at if offer else None,
        ))
        # Documents
        if case is None:
            offer_ok = offer is not None and offer.status == OfferStatus.ACCEPTED.value
            d_status = "current" if offer_ok else "upcoming"
            d_detail = "Open the joining case to request documents." if offer_ok else None
        else:
            docs = db.execute(
                select(OnboardingDocument).where(OnboardingDocument.case_id == case.id)
            ).scalars().all()
            required = [d for d in docs if d.required]
            done_statuses = {DocStatus.ACCEPTED.value, DocStatus.WAIVED.value}
            ready = sum(1 for d in required if d.status in done_statuses)
            d_status = "done" if required and ready == len(required) else "current"
            d_detail = f"{ready} of {len(required)} required documents ready."
        stages.append(_stage(
            "documents", after_label["documents"][0], after_label["documents"][1],
            after_label["documents"][2], d_status, detail=d_detail,
        ))
        # Joining
        if case is not None and case.status == CaseStatus.JOINED.value:
            j_status, j_detail = "done", "Joined."
        elif case is not None and case.status == CaseStatus.READY_TO_JOIN.value:
            j_status, j_detail = "current", "Ready to join."
        elif case is not None and case.joining_date is not None:
            j_status, j_detail = "upcoming", f"Joining on {case.joining_date.isoformat()}."
        else:
            j_status, j_detail = "upcoming", None
        stages.append(_stage(
            "joining", after_label["joining"][0], after_label["joining"][1],
            after_label["joining"][2], j_status, detail=j_detail,
            at=case.joined_at if case else None,
        ))

    current = next(
        (s for s in stages if s.status in {"current", "blocked"} and s.key != "pre_screening"),
        None,
    )
    if closed:
        next_step = "This application is closed. No further steps."
    elif current is None:
        next_step = (
            "Everything is complete." if selected
            else "Waiting for the next event. Nothing is required right now."
        )
    elif current.status == "blocked":
        next_step = current.detail or "This step needs attention."
    else:
        next_step = _NEXT.get(current.key, "Continue with the next step.")
        offer_waiting = offer is not None and offer.status == OfferStatus.ISSUED.value
        if current.key == "offer" and offer_waiting:
            next_step = "Waiting for the candidate to answer the offer."

    return JourneyRead(
        application_id=application.id, campaign_id=application.campaign_id,
        candidate_name=candidate.full_name,
        role_title=campaign.position_title if campaign else "the role",
        application_state=state, current_stage=current.key if current else None,
        next_step=next_step, closed=closed, stages=stages,
    )


def journey_for(db: Session, organisation_id: uuid.UUID, application: Application) -> JourneyRead:
    return build_journey(db, application)

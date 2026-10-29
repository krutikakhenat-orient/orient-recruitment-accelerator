"""Interview workflow ORM models (Req 10.1, 10.2).

InterviewStage groups slots for a campaign (e.g. "Technical", "HR"). InterviewSlot has a
capacity; confirmations cannot exceed it. InterviewInvitation records an authorised
invitation to a candidate's application (interview.approve gated in the service), the
candidate's confirmation, and attendance/no-show. No auto-invite: an invitation only
exists because an authorised actor created it.
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import Enum

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import Uuid

from app.db.base import Actioned, Base, Timestamped, UUIDPrimaryKey


class InterviewMode(str, Enum):
    IN_PERSON = "in_person"
    VIDEO = "video"
    PHONE = "phone"


class InvitationStatus(str, Enum):
    INVITED = "invited"
    CONFIRMED = "confirmed"
    DECLINED = "declined"
    RESCHEDULE_REQUESTED = "reschedule_requested"


class AttendanceStatus(str, Enum):
    PENDING = "pending"
    # New check-in/check-out lifecycle values. CHECKED_IN = arrived, interview in progress;
    # CHECKED_OUT = interview finished (after assessment). ATTENDED / NO_SHOW are legacy
    # values kept for historical invitations recorded before this flow existed.
    CHECKED_IN = "checked_in"
    CHECKED_OUT = "checked_out"
    ATTENDED = "attended"
    NO_SHOW = "no_show"


class InterviewStage(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "interview_stage"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    slots: Mapped[list[InterviewSlot]] = relationship(
        back_populates="stage", cascade="all, delete-orphan", lazy="selectin"
    )


class InterviewSlot(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "interview_slot"

    stage_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("interview_stage.id", ondelete="CASCADE"), nullable=False, index=True
    )
    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    slot_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[str] = mapped_column(String(16), nullable=False)  # "HH:MM"
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default=InterviewMode.IN_PERSON.value
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    stage: Mapped[InterviewStage] = relationship(back_populates="slots")

    @property
    def has_capacity(self) -> bool:
        return self.confirmed_count < self.capacity


class InterviewInvitation(UUIDPrimaryKey, Timestamped, Actioned, Base):
    __tablename__ = "interview_invitation"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    application_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("application.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    stage_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    slot_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)

    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=InvitationStatus.INVITED.value
    )
    attendance: Mapped[str] = mapped_column(
        String(16), nullable=False, default=AttendanceStatus.PENDING.value
    )

    # The authorised approver who issued the invitation (no auto-invite).
    approved_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    invited_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Interview-day check-in / check-out timestamps (the source of truth for the panel
    # lifecycle). Both nullable: a scheduled-but-not-yet-arrived candidate has neither; a
    # checked-in candidate has checked_in_at only; a completed interview has both. They are
    # the authoritative record behind the ``attendance`` display string.
    checked_in_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_out_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    auto_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class InterviewAssignment(UUIDPrimaryKey, Timestamped, Actioned, Base):
    """Which interviewer (panel member) is assigned to interview which campaign/job, and
    optionally which stage within it.

    This is the object-level authorisation link for the interview panel — the interview
    analogue of ``CampaignAssignment`` (which governs recruiter/HR campaign access). Before
    this existed, any holder of ``assessment.submit`` saw the whole organisation's active
    interviews; with it, a panel member sees ONLY the campaigns (and, when scoped, stages)
    they are actively assigned to.

    Scoping model: ``campaign_id`` is required; ``stage_id`` is nullable and NULL means "the
    whole campaign" (the common default). A non-null ``stage_id`` narrows the assignment to
    that interview round.

    Soft removal: ``is_active`` is set False to revoke access while PRESERVING assignment
    history (and, crucially, any assessments the interviewer already submitted — those live
    in a separate table and are never touched). A unique constraint on
    ``(campaign_id, stage_id, interviewer_id)`` gives each logical assignment a single row,
    so a repeated assign request REACTIVATES the existing row rather than inserting a
    duplicate (idempotent).

    Loose coupling: ``campaign_id`` / ``stage_id`` are plain UUIDs without a hard
    cross-module FK, matching ``CampaignAssignment`` / ``InterviewInvitation`` conventions;
    ``interviewer_id`` / ``assigned_by`` reference ``app_user`` (interviewers are ordinary
    users holding the INTERVIEW_PANEL role).
    """

    __tablename__ = "interview_assignment"
    __table_args__ = (
        UniqueConstraint(
            "campaign_id",
            "stage_id",
            "interviewer_id",
            name="uq_interview_assignment_scope",
        ),
    )

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), nullable=False, index=True
    )
    # NULL => the whole campaign; otherwise a specific interview stage of that campaign.
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), nullable=True, index=True
    )
    interviewer_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

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

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String
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
    auto_invite: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

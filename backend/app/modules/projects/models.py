"""Projects ORM model (Req 2.1)."""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Actioned, Base, OptimisticVersion, Timestamped, UUIDPrimaryKey


class Project(UUIDPrimaryKey, Timestamped, Actioned, OptimisticVersion, Base):
    __tablename__ = "project"

    organisation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("organisation.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_unit: Mapped[str | None] = mapped_column(String(255), nullable=True)
    department: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hr_owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_hiring_start: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    planned_hiring_end: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    __table_args__ = ()

    # Convenience for repository scoping.
    def belongs_to(self, organisation_id: uuid.UUID) -> bool:
        return self.organisation_id == organisation_id

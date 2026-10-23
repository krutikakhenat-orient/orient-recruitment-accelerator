"""Interview check-in / check-out timestamps.

Additive-only: two nullable timestamp columns on interview_invitation recording when the
interview panel checked a candidate in and out. Existing invitations leave both null, so
historical rows (including legacy ATTENDED / NO_SHOW attendance) remain valid and are not
rewritten. The new CHECKED_IN / CHECKED_OUT application states and the CHECKED_IN /
CHECKED_OUT attendance strings are plain VARCHAR values and need no schema change.

Revision ID: 0008_interview_check_in_out
Revises: 0007_form_repeating_groups
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_interview_check_in_out"
down_revision: str | None = "0007_form_repeating_groups"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "interview_invitation",
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "interview_invitation",
        sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("interview_invitation", "checked_out_at")
    op.drop_column("interview_invitation", "checked_in_at")

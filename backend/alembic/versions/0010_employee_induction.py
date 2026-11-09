"""Employee induction tables (induction_video, induction_completion).

Additive-only: creates the two tables introduced by the employee induction module, with
the same UUID / timestamp / FK / index conventions as the ORM models
(``app.modules.induction.models``). Without this migration a PostgreSQL deployment that
runs ``alembic upgrade head`` would have no induction tables (local SQLite dev creates them
via ``create_all``, which hid the gap).

No existing table is read, altered or dropped. The downgrade drops only these two tables.

Revision ID: 0010_employee_induction
Revises: 0009_interview_assignment
Create Date: 2026-10-30
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_employee_induction"
down_revision: str | None = "0009_interview_assignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    # Database-neutral UUID (native on PostgreSQL, CHAR(32) on SQLite), matching the ORM.
    return sa.Uuid(as_uuid=True)


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "induction_video",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.String(1024), nullable=True),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisation.id"], ondelete="CASCADE"
        ),
    )
    op.create_index(
        "ix_induction_video_organisation_id", "induction_video", ["organisation_id"]
    )

    op.create_table(
        "induction_completion",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("induction_video_id", _uuid(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["induction_video_id"], ["induction_video.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "user_id", "induction_video_id", name="uq_induction_completion_user_video"
        ),
    )
    op.create_index(
        "ix_induction_completion_organisation_id", "induction_completion",
        ["organisation_id"],
    )
    op.create_index(
        "ix_induction_completion_user_id", "induction_completion", ["user_id"]
    )
    op.create_index(
        "ix_induction_completion_induction_video_id", "induction_completion",
        ["induction_video_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_induction_completion_induction_video_id", table_name="induction_completion"
    )
    op.drop_index("ix_induction_completion_user_id", table_name="induction_completion")
    op.drop_index(
        "ix_induction_completion_organisation_id", table_name="induction_completion"
    )
    op.drop_table("induction_completion")
    op.drop_index("ix_induction_video_organisation_id", table_name="induction_video")
    op.drop_table("induction_video")

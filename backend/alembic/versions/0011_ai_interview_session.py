"""AI voice interview session table (ai_interview_session).

Additive-only: creates the single table used by the AI interview module
(``app.modules.ai_interviews.models``). No existing table is read, altered or dropped.
The downgrade drops only this table.

Revision ID: 0011_ai_interview_session
Revises: 0010_employee_induction
Create Date: 2026-11-06
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_ai_interview_session"
down_revision: str | None = "0010_employee_induction"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "ai_interview_session",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("role_title", sa.String(255), nullable=False),
        sa.Column("question_set", sa.JSON(), nullable=True),
        sa.Column("question_set_version", sa.String(80), nullable=True),
        sa.Column("generated_by", sa.String(32), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("link_token_hash", sa.String(64), nullable=True),
        sa.Column("link_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consent_notice_version", sa.String(40), nullable=True),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("start_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_reason", sa.String(32), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("transcript", sa.JSON(), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_ai_interview_session_organisation_id", "ai_interview_session", ["organisation_id"]
    )
    op.create_index("ix_ai_interview_session_campaign_id", "ai_interview_session", ["campaign_id"])
    op.create_index(
        "ix_ai_interview_session_application_id", "ai_interview_session", ["application_id"]
    )
    op.create_index("ix_ai_interview_session_status", "ai_interview_session", ["status"])
    op.create_index(
        "ix_ai_interview_session_link_token_hash", "ai_interview_session", ["link_token_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_interview_session_link_token_hash", table_name="ai_interview_session")
    op.drop_index("ix_ai_interview_session_status", table_name="ai_interview_session")
    op.drop_index("ix_ai_interview_session_application_id", table_name="ai_interview_session")
    op.drop_index("ix_ai_interview_session_campaign_id", table_name="ai_interview_session")
    op.drop_index("ix_ai_interview_session_organisation_id", table_name="ai_interview_session")
    op.drop_table("ai_interview_session")

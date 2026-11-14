"""AI interview video evidence table (ai_interview_recording).

Additive-only: creates one new table used by ``app.modules.ai_interviews`` for the optional,
consented video recording of an interview attempt. No existing table is altered or dropped.
The downgrade drops only this table (video bytes in the object store are removed separately by
the retention purge).

Revision ID: 0013_ai_interview_recording
Revises: 0012_long_term_automation
Create Date: 2026-11-12
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_ai_interview_recording"
down_revision: str | None = "0012_long_term_automation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ai_interview_recording"
_INDEXED = (
    "organisation_id",
    "session_id",
    "campaign_id",
    "status",
    "upload_token_hash",
    "delete_after",
)


def _uuid() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("session_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("attempt_start", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("consent_notice_version", sa.String(40), nullable=False),
        sa.Column("consent_given_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("upload_token_hash", sa.String(64), nullable=True),
        sa.Column("upload_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("storage_prefix", sa.String(255), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("bytes_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("assembled_key", sa.String(255), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["ai_interview_session.id"], ondelete="CASCADE"),
        sa.CheckConstraint("chunk_count >= 0 AND bytes_total >= 0", name="ck_recording_sizes"),
    )
    for column in _INDEXED:
        op.create_index(f"ix_{_TABLE}_{column}", _TABLE, [column])


def downgrade() -> None:
    for column in reversed(_INDEXED):
        op.drop_index(f"ix_{_TABLE}_{column}", table_name=_TABLE)
    op.drop_table(_TABLE)

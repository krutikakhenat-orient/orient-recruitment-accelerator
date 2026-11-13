"""HR policy chatbot: policy file/index columns, sync requests, feedback, HR questions.

Additive-only. Adds nullable (or defaulted) columns to ``policy_document`` and
``assistant_query_log`` and creates ``kb_sync_request``, ``assistant_feedback`` and
``hr_question``. ``assistant_query_log`` still carries NO user identifier (Req 8.1).
The downgrade drops only what this revision adds.

Revision ID: 0014_hr_policy_chatbot
Revises: 0013_ai_interview_recording
Create Date: 2026-11-13
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014_hr_policy_chatbot"
down_revision: str | None = "0013_ai_interview_recording"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, dict[str, object]], ...] = (
    ("source_key", sa.String(512), {}),
    ("source_filename", sa.String(255), {}),
    ("source_content_type", sa.String(128), {}),
    ("content_hash", sa.String(64), {}),
    ("approved_key", sa.String(512), {}),
    ("index_status", sa.String(16), {"server_default": "not_indexed"}),
    ("index_error", sa.String(500), {}),
    ("kb_sync_request_id", sa.Uuid(as_uuid=True), {}),
    ("ingestion_job_id", sa.String(128), {}),
    ("indexed_at", sa.DateTime(timezone=True), {}),
    ("review_due_date", sa.Date(), {}),
    ("audience", sa.JSON(), {}),
)
_POLICY_INDEXED = ("content_hash", "index_status", "kb_sync_request_id")

_LOG_COLUMNS: tuple[tuple[str, sa.types.TypeEngine], ...] = (
    ("answered_via", sa.String(16)),
    ("retrieved_count", sa.Integer()),
    ("top_score", sa.Float()),
    ("latency_ms", sa.Integer()),
    ("outcome", sa.String(24)),
)


def _uuid() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=True)


def _timestamps() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    ]


def upgrade() -> None:
    with op.batch_alter_table("policy_document") as batch:
        for name, type_, kwargs in _POLICY_COLUMNS:
            nullable = name != "index_status"
            batch.add_column(sa.Column(name, type_, nullable=nullable, **kwargs))  # type: ignore[arg-type]
    for column in _POLICY_INDEXED:
        op.create_index(f"ix_policy_document_{column}", "policy_document", [column])

    with op.batch_alter_table("assistant_query_log") as batch:
        for name, type_ in _LOG_COLUMNS:
            batch.add_column(sa.Column(name, type_, nullable=True))

    op.create_table(
        "kb_sync_request",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("ingestion_job_id", sa.String(128), nullable=True),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed')", name="ck_kb_sync_status"
        ),
    )
    op.create_index("ix_kb_sync_request_organisation_id", "kb_sync_request", ["organisation_id"])
    op.create_index("ix_kb_sync_request_status", "kb_sync_request", ["status"])

    op.create_table(
        "assistant_feedback",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("query_log_id", _uuid(), nullable=False),
        sa.Column("helpful", sa.Boolean(), nullable=False),
        sa.Column("comment", sa.String(300), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["query_log_id"], ["assistant_query_log.id"],
                                ondelete="CASCADE"),
        sa.UniqueConstraint("query_log_id", name="uq_assistant_feedback_query"),
    )
    op.create_index("ix_assistant_feedback_organisation_id", "assistant_feedback",
                    ["organisation_id"])
    op.create_index("ix_assistant_feedback_query_log_id", "assistant_feedback",
                    ["query_log_id"])

    op.create_table(
        "hr_question",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("asked_by", _uuid(), nullable=False),
        sa.Column("question", sa.String(300), nullable=False),
        sa.Column("contact_preference", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("answered_by", _uuid(), nullable=True),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idempotency_key", sa.String(80), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asked_by"], ["app_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organisation_id", "asked_by", "idempotency_key",
                            name="uq_hr_question_idempotency"),
        sa.CheckConstraint(
            "status IN ('open', 'answered', 'closed')", name="ck_hr_question_status"
        ),
    )
    for column in ("organisation_id", "asked_by", "status"):
        op.create_index(f"ix_hr_question_{column}", "hr_question", [column])


def downgrade() -> None:
    for column in ("status", "asked_by", "organisation_id"):
        op.drop_index(f"ix_hr_question_{column}", table_name="hr_question")
    op.drop_table("hr_question")
    op.drop_index("ix_assistant_feedback_query_log_id", table_name="assistant_feedback")
    op.drop_index("ix_assistant_feedback_organisation_id", table_name="assistant_feedback")
    op.drop_table("assistant_feedback")
    op.drop_index("ix_kb_sync_request_status", table_name="kb_sync_request")
    op.drop_index("ix_kb_sync_request_organisation_id", table_name="kb_sync_request")
    op.drop_table("kb_sync_request")

    with op.batch_alter_table("assistant_query_log") as batch:
        for name, _ in reversed(_LOG_COLUMNS):
            batch.drop_column(name)
    for column in reversed(_POLICY_INDEXED):
        op.drop_index(f"ix_policy_document_{column}", table_name="policy_document")
    with op.batch_alter_table("policy_document") as batch:
        for name, _, _ in reversed(_POLICY_COLUMNS):
            batch.drop_column(name)

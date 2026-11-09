"""Long-term automation tables: notifications, SLA, offers, onboarding, policies, confirmations.

Additive-only: creates new tables used by the notifications, sla, onboarding, policies and
interview_confirmations modules. No existing table is altered or dropped. The downgrade
drops only these tables.

Revision ID: 0012_long_term_automation
Revises: 0011_ai_interview_session
Create Date: 2026-11-07
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_long_term_automation"
down_revision: str | None = "0011_ai_interview_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    return sa.Uuid(as_uuid=True)


def _pk() -> sa.Column:
    return sa.Column("id", _uuid(), primary_key=True)


def _org() -> sa.Column:
    return sa.Column(
        "organisation_id", _uuid(), sa.ForeignKey("organisation.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
                  nullable=False),
    ]


def _actioned() -> list[sa.Column]:
    return [
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
    ]


def upgrade() -> None:
    # ---- notifications -------------------------------------------------------
    op.create_table(
        "notification_template",
        _pk(), _org(),
        sa.Column("key", sa.String(64), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(255), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_actioned(), *_stamps(),
        sa.UniqueConstraint("organisation_id", "key", "version", name="uq_notification_template_ver"),
    )
    op.create_table(
        "notification_delivery",
        _pk(), _org(),
        sa.Column("campaign_id", _uuid(), nullable=True, index=True),
        sa.Column("application_id", _uuid(), nullable=True, index=True),
        sa.Column("onboarding_case_id", _uuid(), nullable=True, index=True),
        sa.Column("template_key", sa.String(64), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False),
        sa.Column("recipient", sa.String(320), nullable=False),
        sa.Column("subject", sa.String(255), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("provider_response_id", sa.String(255), nullable=True),
        sa.Column("failure_reason", sa.String(500), nullable=True),
        sa.Column("manual_link", sa.String(2000), nullable=True),
        sa.Column("triggered_by", _uuid(), nullable=True),
        *_stamps(),
    )

    # ---- SLA -----------------------------------------------------------------
    op.create_table(
        "sla_policy",
        _pk(), _org(),
        sa.Column("campaign_id", _uuid(), nullable=True, index=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("at_risk_percent", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_actioned(), *_stamps(),
    )
    op.create_table(
        "sla_escalation",
        _pk(), _org(),
        sa.Column("campaign_id", _uuid(), nullable=False, index=True),
        sa.Column("application_id", _uuid(), sa.ForeignKey("application.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("delivery_id", _uuid(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        *_stamps(),
    )

    # ---- offers and onboarding -------------------------------------------------
    op.create_table(
        "offer",
        _pk(), _org(),
        sa.Column("application_id", _uuid(), sa.ForeignKey("application.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("campaign_id", _uuid(), nullable=False, index=True),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("respond_by", sa.Date(), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        *_actioned(), *_stamps(),
    )
    op.create_table(
        "onboarding_case",
        _pk(), _org(),
        sa.Column("application_id", _uuid(), sa.ForeignKey("application.id", ondelete="CASCADE"),
                  nullable=False, unique=True, index=True),
        sa.Column("campaign_id", _uuid(), nullable=False, index=True),
        sa.Column("candidate_id", _uuid(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("joining_date", sa.Date(), nullable=True),
        sa.Column("reporting_manager", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("work_location", sa.String(255), nullable=True),
        sa.Column("role_expectations", sa.Text(), nullable=True),
        sa.Column("content_approved", sa.Boolean(), nullable=False),
        sa.Column("content_approved_by", _uuid(), nullable=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        *_actioned(), *_stamps(),
    )
    op.create_table(
        "onboarding_document",
        _pk(), _org(),
        sa.Column("case_id", _uuid(), sa.ForeignKey("onboarding_case.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name_on_document", sa.String(255), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("note", sa.String(500), nullable=True),
        *_stamps(),
    )
    op.create_table(
        "onboarding_document_flag",
        _pk(), _org(),
        sa.Column("case_id", _uuid(), sa.ForeignKey("onboarding_case.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("onboarding_document_id", _uuid(), nullable=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("source", sa.String(24), nullable=False),
        sa.Column("resolved_by", _uuid(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_reason", sa.String(500), nullable=True),
        *_stamps(),
    )

    # ---- policies and assistant ------------------------------------------------
    op.create_table(
        "policy_document",
        _pk(), _org(),
        sa.Column("family_id", _uuid(), nullable=False, index=True),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("department", sa.String(120), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, index=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        *_actioned(), *_stamps(),
    )
    op.create_table(
        "policy_acknowledgement",
        _pk(), _org(),
        sa.Column("policy_id", _uuid(), sa.ForeignKey("policy_document.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("user_id", _uuid(), sa.ForeignKey("app_user.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=False),
        *_stamps(),
        sa.UniqueConstraint("policy_id", "user_id", name="uq_policy_ack_policy_user"),
    )
    op.create_table(
        "assistant_query_log",
        _pk(), _org(),
        sa.Column("question", sa.String(300), nullable=False),
        sa.Column("answered", sa.Boolean(), nullable=False),
        sa.Column("policy_id", _uuid(), nullable=True),
        *_stamps(),
    )

    # ---- interview confirmations -----------------------------------------------
    op.create_table(
        "interview_confirmation_link",
        _pk(), _org(),
        sa.Column("invitation_id", _uuid(),
                  sa.ForeignKey("interview_invitation.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("token_hash", sa.String(64), nullable=False, index=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.String(24), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        *_stamps(),
    )


def downgrade() -> None:
    for table in (
        "interview_confirmation_link",
        "assistant_query_log",
        "policy_acknowledgement",
        "policy_document",
        "onboarding_document_flag",
        "onboarding_document",
        "onboarding_case",
        "offer",
        "sla_escalation",
        "sla_policy",
        "notification_delivery",
        "notification_template",
    ):
        op.drop_table(table)

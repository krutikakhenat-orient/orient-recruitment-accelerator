"""Phase 5-7: interviews, assessments, decisions, waitlist, privacy, retention.

Revision ID: 0005_interviews_governance
Revises: 0004_rules_screening
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_interviews_governance"
down_revision: str | None = "0004_rules_screening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=False)


def _org_fk() -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"],
                                   ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "interview_stage",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"), _org_fk(),
    )
    op.create_index("ix_interview_stage_organisation_id", "interview_stage",
                    ["organisation_id"])
    op.create_index("ix_interview_stage_campaign_id", "interview_stage", ["campaign_id"])

    op.create_table(
        "interview_slot",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("stage_id", _uuid(), nullable=False),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("slot_date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.String(16), nullable=False),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="in_person"),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("confirmed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["stage_id"], ["interview_stage.id"], ondelete="CASCADE"),
        _org_fk(),
    )
    op.create_index("ix_interview_slot_stage_id", "interview_slot", ["stage_id"])
    op.create_index("ix_interview_slot_organisation_id", "interview_slot",
                    ["organisation_id"])

    op.create_table(
        "interview_invitation",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("stage_id", _uuid(), nullable=True),
        sa.Column("slot_id", _uuid(), nullable=True),
        sa.Column("status", sa.String(24), nullable=False, server_default="invited"),
        sa.Column("attendance", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("approved_by", _uuid(), nullable=False),
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("auto_invite", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        _org_fk(),
    )
    op.create_index("ix_interview_invitation_organisation_id", "interview_invitation",
                    ["organisation_id"])
    op.create_index("ix_interview_invitation_application_id", "interview_invitation",
                    ["application_id"])
    op.create_index("ix_interview_invitation_campaign_id", "interview_invitation",
                    ["campaign_id"])

    op.create_table(
        "assessment",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("panel_member_id", _uuid(), nullable=False),
        sa.Column("criteria_scores", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("problem_solving_notes", sa.Text(), nullable=True),
        sa.Column("role_understanding_notes", sa.Text(), nullable=True),
        sa.Column("interview_notes", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(16), nullable=False),
        sa.Column("conflict_declared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("conflict_detail", sa.Text(), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        _org_fk(),
    )
    op.create_index("ix_assessment_organisation_id", "assessment", ["organisation_id"])
    op.create_index("ix_assessment_application_id", "assessment", ["application_id"])
    op.create_index("ix_assessment_campaign_id", "assessment", ["campaign_id"])

    op.create_table(
        "hiring_decision",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("decision_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="recommended"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("recommended_by", _uuid(), nullable=False),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        _org_fk(),
    )
    op.create_index("ix_hiring_decision_organisation_id", "hiring_decision",
                    ["organisation_id"])
    op.create_index("ix_hiring_decision_application_id", "hiring_decision",
                    ["application_id"])
    op.create_index("ix_hiring_decision_campaign_id", "hiring_decision", ["campaign_id"])

    op.create_table(
        "waitlist_record",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("screening_run_id", _uuid(), nullable=True),
        sa.Column("eligibility_state", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("candidate_communication_status", sa.String(32), nullable=False,
                  server_default="not_notified"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
        _org_fk(),
    )
    op.create_index("ix_waitlist_record_organisation_id", "waitlist_record",
                    ["organisation_id"])
    op.create_index("ix_waitlist_record_application_id", "waitlist_record",
                    ["application_id"])
    op.create_index("ix_waitlist_record_campaign_id", "waitlist_record", ["campaign_id"])

    op.create_table(
        "privacy_request",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("candidate_id", _uuid(), nullable=False),
        sa.Column("request_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="received"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("handled_by", _uuid(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"], ondelete="CASCADE"),
        _org_fk(),
    )
    op.create_index("ix_privacy_request_organisation_id", "privacy_request",
                    ["organisation_id"])
    op.create_index("ix_privacy_request_candidate_id", "privacy_request", ["candidate_id"])

    op.create_table(
        "retention_policy",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("retain_days", sa.Integer(), nullable=False),
        sa.Column("action_on_expiry", sa.String(16), nullable=False),
        sa.Column("legal_hold", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"), _org_fk(),
    )
    op.create_index("ix_retention_policy_organisation_id", "retention_policy",
                    ["organisation_id"])

    op.create_table(
        "retention_action",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("action_type", sa.String(16), nullable=False),
        sa.Column("target_entity_type", sa.String(64), nullable=False),
        sa.Column("target_entity_id", sa.String(64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"), _org_fk(),
    )
    op.create_index("ix_retention_action_organisation_id", "retention_action",
                    ["organisation_id"])


def downgrade() -> None:
    op.drop_table("retention_action")
    op.drop_table("retention_policy")
    op.drop_table("privacy_request")
    op.drop_table("waitlist_record")
    op.drop_table("hiring_decision")
    op.drop_table("assessment")
    op.drop_table("interview_invitation")
    op.drop_table("interview_slot")
    op.drop_table("interview_stage")

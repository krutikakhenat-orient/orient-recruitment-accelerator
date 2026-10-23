"""Phase 4: rules, thresholds, screening runs, criterion results, review queue.

Revision ID: 0004_rules_screening
Revises: 0003_candidate_application
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_rules_screening"
down_revision: str | None = "0003_candidate_application"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "rule_set",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_rule_set_organisation_id", "rule_set", ["organisation_id"])
    op.create_index("ix_rule_set_campaign_id", "rule_set", ["campaign_id"])

    op.create_table(
        "rule_set_version",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("rule_set_id", _uuid(), nullable=False),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("rules", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["rule_set_id"], ["rule_set.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("rule_set_id", "version_number", name="uq_rule_set_version_number"),
    )
    op.create_index("ix_rule_set_version_rule_set_id", "rule_set_version", ["rule_set_id"])
    op.create_index("ix_rule_set_version_organisation_id", "rule_set_version",
                    ["organisation_id"])

    op.create_table(
        "threshold_set",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("four_eyes_required", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_threshold_set_organisation_id", "threshold_set", ["organisation_id"])
    op.create_index("ix_threshold_set_campaign_id", "threshold_set", ["campaign_id"])

    op.create_table(
        "threshold_version",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("threshold_set_id", _uuid(), nullable=False),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("review_below", sa.Float(), nullable=False, server_default="50"),
        sa.Column("recommend_at_or_above", sa.Float(), nullable=False, server_default="70"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["threshold_set_id"], ["threshold_set.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("threshold_set_id", "version_number",
                            name="uq_threshold_version_number"),
    )
    op.create_index("ix_threshold_version_threshold_set_id", "threshold_version",
                    ["threshold_set_id"])
    op.create_index("ix_threshold_version_organisation_id", "threshold_version",
                    ["organisation_id"])

    op.create_table(
        "screening_run",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("jd_version_id", _uuid(), nullable=True),
        sa.Column("rule_set_version_id", _uuid(), nullable=False),
        sa.Column("threshold_version_id", _uuid(), nullable=True),
        sa.Column("form_version_id", _uuid(), nullable=True),
        _ts("started_at"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("eligibility_outcome", sa.String(32), nullable=False),
        sa.Column("confidence_status", sa.String(32), nullable=False),
        sa.Column("recommendation", sa.String(48), nullable=False),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("processing_errors", sa.Text(), nullable=True),
        sa.Column("input_data_hash", sa.String(64), nullable=False),
        sa.Column("engine_version", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_screening_run_organisation_id", "screening_run", ["organisation_id"])
    op.create_index("ix_screening_run_application_id", "screening_run", ["application_id"])

    op.create_table(
        "criterion_result",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("screening_run_id", _uuid(), nullable=False),
        sa.Column("criterion_name", sa.String(255), nullable=False),
        sa.Column("criterion_type", sa.String(48), nullable=False),
        sa.Column("mandatory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("expected", sa.Text(), nullable=True),
        sa.Column("candidate_evidence", sa.Text(), nullable=True),
        sa.Column("evidence_source", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("max_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("awarded_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["screening_run_id"], ["screening_run.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_criterion_result_screening_run_id", "criterion_result",
                    ["screening_run_id"])

    op.create_table(
        "review_item",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("reason", sa.String(48), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("screening_run_id", _uuid(), nullable=True),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_review_item_organisation_id", "review_item", ["organisation_id"])
    op.create_index("ix_review_item_application_id", "review_item", ["application_id"])
    op.create_index("ix_review_item_campaign_id", "review_item", ["campaign_id"])

    op.create_table(
        "review_action",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("review_item_id", _uuid(), nullable=False),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("action_type", sa.String(48), nullable=False),
        sa.Column("original_value", sa.Text(), nullable=True),
        sa.Column("corrected_value", sa.Text(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("actor_id", _uuid(), nullable=False),
        sa.Column("resolves_item", sa.Boolean(), nullable=False, server_default=sa.false()),
        _ts("created_at"), _ts("updated_at"),
        sa.ForeignKeyConstraint(["review_item_id"], ["review_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_review_action_review_item_id", "review_action", ["review_item_id"])
    op.create_index("ix_review_action_organisation_id", "review_action", ["organisation_id"])


def downgrade() -> None:
    op.drop_table("review_action")
    op.drop_table("review_item")
    op.drop_table("criterion_result")
    op.drop_table("screening_run")
    op.drop_table("threshold_version")
    op.drop_table("threshold_set")
    op.drop_table("rule_set_version")
    op.drop_table("rule_set")

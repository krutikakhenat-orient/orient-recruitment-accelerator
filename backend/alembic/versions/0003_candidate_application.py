"""Phase 3: candidates, consent, applications, extracted fields, skills.

Revision ID: 0003_candidate_application
Revises: 0002_campaign_jd
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_candidate_application"
down_revision: str | None = "0002_campaign_jd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "candidate",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("mobile", sa.String(32), nullable=True),
        sa.Column("in_talent_pool", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_candidate_organisation_id", "candidate", ["organisation_id"])
    op.create_index("ix_candidate_email", "candidate", ["email"])

    op.create_table(
        "consent_record",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("candidate_id", _uuid(), nullable=False),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="granted"),
        sa.Column("notice_version", sa.String(64), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_consent_record_organisation_id", "consent_record", ["organisation_id"])
    op.create_index("ix_consent_record_candidate_id", "consent_record", ["candidate_id"])

    op.create_table(
        "candidate_duplicate_link",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("candidate_id", _uuid(), nullable=False),
        sa.Column("duplicate_of_id", _uuid(), nullable=False),
        sa.Column("reason", sa.String(255), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resolved_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["duplicate_of_id"], ["candidate.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_candidate_duplicate_link_organisation_id",
                    "candidate_duplicate_link", ["organisation_id"])
    op.create_index("ix_candidate_duplicate_link_candidate_id",
                    "candidate_duplicate_link", ["candidate_id"])
    op.create_index("ix_candidate_duplicate_link_duplicate_of_id",
                    "candidate_duplicate_link", ["duplicate_of_id"])

    op.create_table(
        "application",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("candidate_id", _uuid(), nullable=False),
        sa.Column("form_version_id", _uuid(), nullable=False),
        sa.Column("answers", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("resume_document_id", _uuid(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="submitted"),
        sa.Column("disposition_reason", sa.String(1000), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("campaign_id", "candidate_id",
                            name="uq_application_campaign_candidate"),
    )
    op.create_index("ix_application_organisation_id", "application", ["organisation_id"])
    op.create_index("ix_application_campaign_id", "application", ["campaign_id"])
    op.create_index("ix_application_candidate_id", "application", ["candidate_id"])
    op.create_index("ix_application_state", "application", ["state"])

    op.create_table(
        "extracted_field",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("application_id", _uuid(), nullable=False),
        sa.Column("source_document_id", _uuid(), nullable=True),
        sa.Column("field_name", sa.String(64), nullable=False),
        sa.Column("extracted_value", sa.Text(), nullable=True),
        sa.Column("verified_value", sa.Text(), nullable=True),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("source_span", sa.Text(), nullable=True),
        sa.Column("extraction_method", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="unverified"),
        sa.Column("verified_by", _uuid(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("correction_reason", sa.Text(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["application_id"], ["application.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_extracted_field_organisation_id", "extracted_field",
                    ["organisation_id"])
    op.create_index("ix_extracted_field_application_id", "extracted_field",
                    ["application_id"])

    op.create_table(
        "skill",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("canonical_name", sa.String(128), nullable=False),
        sa.Column("category", sa.String(64), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organisation_id", "canonical_name", name="uq_skill_org_name"),
    )
    op.create_index("ix_skill_organisation_id", "skill", ["organisation_id"])

    op.create_table(
        "skill_alias",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("skill_id", _uuid(), nullable=False),
        sa.Column("alias", sa.String(128), nullable=False),
        sa.Column("relationship_type", sa.String(32), nullable=False),
        sa.Column("approved_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["skill_id"], ["skill.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("organisation_id", "alias", name="uq_skill_alias"),
    )
    op.create_index("ix_skill_alias_organisation_id", "skill_alias", ["organisation_id"])
    op.create_index("ix_skill_alias_skill_id", "skill_alias", ["skill_id"])


def downgrade() -> None:
    op.drop_table("skill_alias")
    op.drop_table("skill")
    op.drop_table("extracted_field")
    op.drop_table("application")
    op.drop_table("candidate_duplicate_link")
    op.drop_table("consent_record")
    op.drop_table("candidate")

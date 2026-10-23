"""Phase 2: projects, campaigns, documents, job descriptions, form schemas.

Revision ID: 0002_campaign_jd
Revises: 0001_foundation
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_campaign_jd"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> sa.types.TypeEngine:
    return postgresql.UUID(as_uuid=True)


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(),
                     nullable=False)


def upgrade() -> None:
    op.create_table(
        "project",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("business_unit", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("business_owner", sa.String(255), nullable=True),
        sa.Column("hr_owner", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("planned_hiring_start", sa.Date(), nullable=True),
        sa.Column("planned_hiring_end", sa.Date(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_project_organisation_id", "project", ["organisation_id"])

    op.create_table(
        "campaign",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("project_id", _uuid(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("position_title", sa.String(255), nullable=False),
        sa.Column("campaign_type", sa.String(64), nullable=True),
        sa.Column("number_of_openings", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("employment_type", sa.String(64), nullable=True),
        sa.Column("work_location", sa.String(255), nullable=True),
        sa.Column("work_mode", sa.String(64), nullable=True),
        sa.Column("hiring_manager_id", _uuid(), nullable=True),
        sa.Column("recruiter_id", _uuid(), nullable=True),
        sa.Column("application_opening_date", sa.Date(), nullable=True),
        sa.Column("application_closing_date", sa.Date(), nullable=True),
        sa.Column("state", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("approved_jd_version_id", _uuid(), nullable=True),
        sa.Column("approved_rule_set_version_id", _uuid(), nullable=True),
        sa.Column("approved_form_version_id", _uuid(), nullable=True),
        sa.Column("active_threshold_version_id", _uuid(), nullable=True),
        sa.Column("privacy_notice_version", sa.String(64), nullable=True),
        sa.Column("retention_policy", sa.String(64), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("published_by", _uuid(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"], ondelete="RESTRICT"),
    )
    op.create_index("ix_campaign_organisation_id", "campaign", ["organisation_id"])
    op.create_index("ix_campaign_project_id", "campaign", ["project_id"])
    op.create_index("ix_campaign_state", "campaign", ["state"])

    op.create_table(
        "document",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="quarantined"),
        sa.Column("original_filename", sa.String(512), nullable=False),
        sa.Column("storage_key", sa.String(256), nullable=False, unique=True),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("scan_result", sa.String(255), nullable=True),
        sa.Column("rejection_reason", sa.String(255), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_document_organisation_id", "document", ["organisation_id"])
    op.create_index("ix_document_sha256", "document", ["sha256"])

    op.create_table(
        "job_description",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_job_description_organisation_id", "job_description",
                    ["organisation_id"])
    op.create_index("ix_job_description_campaign_id", "job_description", ["campaign_id"])

    op.create_table(
        "jd_version",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("job_description_id", _uuid(), nullable=False),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("source_document_id", _uuid(), nullable=True),
        sa.Column("position_title", sa.String(255), nullable=True),
        sa.Column("department", sa.String(255), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("work_mode", sa.String(64), nullable=True),
        sa.Column("employment_type", sa.String(64), nullable=True),
        sa.Column("number_of_openings", sa.Integer(), nullable=True),
        sa.Column("minimum_total_experience_years", sa.Float(), nullable=True),
        sa.Column("minimum_relevant_experience_years", sa.Float(), nullable=True),
        sa.Column("responsibilities", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("mandatory_skills", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("desirable_skills", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("extraction_draft", postgresql.JSONB(), nullable=True),
        sa.Column("approved_by", _uuid(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_reason", sa.Text(), nullable=True),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["job_description_id"], ["job_description.id"],
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("job_description_id", "version_number",
                            name="uq_jd_version_number"),
    )
    op.create_index("ix_jd_version_job_description_id", "jd_version", ["job_description_id"])
    op.create_index("ix_jd_version_organisation_id", "jd_version", ["organisation_id"])

    op.create_table(
        "form_schema",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_form_schema_organisation_id", "form_schema", ["organisation_id"])
    op.create_index("ix_form_schema_campaign_id", "form_schema", ["campaign_id"])

    op.create_table(
        "form_version",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("form_schema_id", _uuid(), nullable=False),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("compensation_enabled", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["form_schema_id"], ["form_schema.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organisation_id"], ["organisation.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("form_schema_id", "version_number", name="uq_form_version_number"),
    )
    op.create_index("ix_form_version_form_schema_id", "form_version", ["form_schema_id"])
    op.create_index("ix_form_version_organisation_id", "form_version", ["organisation_id"])

    op.create_table(
        "form_field",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("form_version_id", _uuid(), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("field_class", sa.String(32), nullable=False),
        sa.Column("field_type", sa.String(32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("options", postgresql.JSONB(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["form_version_id"], ["form_version.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_form_field_form_version_id", "form_field", ["form_version_id"])


def downgrade() -> None:
    op.drop_table("form_field")
    op.drop_table("form_version")
    op.drop_table("form_schema")
    op.drop_table("jd_version")
    op.drop_table("job_description")
    op.drop_table("document")
    op.drop_table("campaign")
    op.drop_table("project")

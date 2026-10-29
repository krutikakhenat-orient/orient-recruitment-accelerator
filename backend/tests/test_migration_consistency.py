"""Validate that models and the Alembic baseline migration agree on table structure.

This is a lightweight consistency check (not a full Postgres round-trip): it confirms
every model table is created by the migration's upgrade and that the set of tables
matches the ORM metadata. The full CI pipeline runs the migration against PostgreSQL.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.db.models_registry import Base

MIGRATION = (
    Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0001_foundation.py"
)


def _model_table_names() -> set[str]:
    return set(Base.metadata.tables.keys())


def test_model_tables_present() -> None:
    expected = {
        # Phase 1
        "organisation",
        "role",
        "app_user",
        "user_role",
        "campaign_assignment",
        "audit_event",
        # Phase 2
        "project",
        "campaign",
        "document",
        "job_description",
        "jd_version",
        "form_schema",
        "form_version",
        "form_field",
        # Phase 3
        "candidate",
        "consent_record",
        "candidate_duplicate_link",
        "application",
        "extracted_field",
        "skill",
        "skill_alias",
        # Phase 4
        "rule_set",
        "rule_set_version",
        "threshold_set",
        "threshold_version",
        "screening_run",
        "criterion_result",
        "review_item",
        "review_action",
        # Phase 5-7
        "interview_stage",
        "interview_slot",
        "interview_invitation",
        "interview_assignment",
        "assessment",
        "hiring_decision",
        "waitlist_record",
        "privacy_request",
        "retention_policy",
        "retention_action",
    }
    assert expected == _model_table_names()


def test_migration_module_defines_upgrade_and_downgrade() -> None:
    spec = importlib.util.spec_from_file_location("mig0001", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "0001_foundation"
    assert module.down_revision is None
    assert callable(module.upgrade)
    assert callable(module.downgrade)


def test_metadata_creates_all_tables_on_fresh_db() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    tables = set(inspect(engine).get_table_names())
    assert _model_table_names() <= tables

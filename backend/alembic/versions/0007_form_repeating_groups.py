"""Repeating-group column schema on form fields (education / work history tables).

Additive-only: a single nullable JSON column holding the row column definitions for a
repeating_group field. Simple fields leave it null, so existing rows remain valid.

Revision ID: 0007_form_repeating_groups
Revises: 0006_skill_tiers_conflict_pii
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_form_repeating_groups"
down_revision: str | None = "0006_skill_tiers_conflict_pii"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("form_field", sa.Column("item_schema", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("form_field", "item_schema")

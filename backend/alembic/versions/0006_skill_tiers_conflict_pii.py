"""Skill-tier label, self-assessment conflict flags, and candidate LinkedIn.

Additive columns only — no destructive changes, so existing rows and prior screening runs
remain valid and reproducible.

Revision ID: 0006_skill_tiers_conflict_pii
Revises: 0005_interviews_governance
Create Date: 2026-10-08
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_skill_tiers_conflict_pii"
down_revision: str | None = "0005_interviews_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Skill-checklist tier label on each criterion result (passthrough; never affects score).
    op.add_column("criterion_result", sa.Column("tier", sa.String(16), nullable=True))

    # Self-assessment conflict signal on a screening run. Defaults preserve existing rows.
    op.add_column(
        "screening_run",
        sa.Column("conflict_flagged", sa.Boolean(), nullable=False,
                  server_default=sa.false()),
    )
    op.add_column(
        "screening_run", sa.Column("conflict_detail", sa.Text(), nullable=True)
    )

    # Optional LinkedIn contact field on candidate (masked by default in the API).
    op.add_column("candidate", sa.Column("linkedin", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("candidate", "linkedin")
    op.drop_column("screening_run", "conflict_detail")
    op.drop_column("screening_run", "conflict_flagged")
    op.drop_column("criterion_result", "tier")

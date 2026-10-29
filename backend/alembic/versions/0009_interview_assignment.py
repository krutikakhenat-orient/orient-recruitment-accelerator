"""Interviewer assignment + interview.assign permission grant.

Additive-only, non-destructive:
  * Creates the ``interview_assignment`` table (object-level link: which panel member
    interviews which campaign/stage), with the same UUID / timestamp / FK / index
    conventions as ``campaign_assignment`` and ``interview_invitation``. A unique constraint
    on (campaign_id, stage_id, interviewer_id) gives each logical assignment a single row so
    re-assignment reactivates rather than duplicates.
  * Grants the new ``interview.assign`` permission to EXISTING ``recruiter_admin`` and
    ``system_admin`` role rows by appending it to their ``permissions`` JSON array (only if
    absent). This mirrors how roles are seeded (roles store a permissions array; there is no
    separate permission table). It is engine-portable: the array is read, updated in Python,
    and written back, so it works on both PostgreSQL (JSONB) and SQLite (JSON) without raw
    SQL JSON functions.

No existing candidates, campaigns, applications, interviews, assessments, or scorecards are
read, modified, or deleted. No table is dropped or recreated. The downgrade drops only the
new table and removes the appended permission.

Revision ID: 0009_interview_assignment
Revises: 0008_interview_check_in_out
Create Date: 2026-10-08
"""
from __future__ import annotations

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_interview_assignment"
down_revision: str | None = "0008_interview_check_in_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PERMISSION = "interview.assign"
_ROLES_TO_GRANT = ("recruiter_admin", "system_admin")


def _uuid() -> sa.types.TypeEngine:
    # Database-neutral UUID (native on PostgreSQL, CHAR(32) on SQLite), matching the ORM.
    return sa.Uuid(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "interview_assignment",
        sa.Column("id", _uuid(), primary_key=True),
        sa.Column("organisation_id", _uuid(), nullable=False),
        sa.Column("campaign_id", _uuid(), nullable=False),
        sa.Column("stage_id", _uuid(), nullable=True),
        sa.Column("interviewer_id", _uuid(), nullable=False),
        sa.Column("assigned_by", _uuid(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", _uuid(), nullable=True),
        sa.Column("updated_by", _uuid(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organisation_id"], ["organisation.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["interviewer_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "campaign_id", "stage_id", "interviewer_id",
            name="uq_interview_assignment_scope",
        ),
    )
    op.create_index(
        "ix_interview_assignment_organisation_id", "interview_assignment",
        ["organisation_id"],
    )
    op.create_index(
        "ix_interview_assignment_campaign_id", "interview_assignment", ["campaign_id"]
    )
    op.create_index(
        "ix_interview_assignment_stage_id", "interview_assignment", ["stage_id"]
    )
    op.create_index(
        "ix_interview_assignment_interviewer_id", "interview_assignment",
        ["interviewer_id"],
    )

    _grant_permission()


def _grant_permission() -> None:
    """Append ``interview.assign`` to existing recruiter_admin / system_admin roles."""
    bind = op.get_bind()
    role = sa.table(
        "role",
        sa.column("id", _uuid()),
        sa.column("name", sa.String()),
        sa.column("permissions", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(role.c.id, role.c.name, role.c.permissions).where(
            role.c.name.in_(_ROLES_TO_GRANT)
        )
    ).fetchall()
    for row in rows:
        perms = _as_list(row.permissions)
        if _PERMISSION in perms:
            continue
        perms.append(_PERMISSION)
        perms = sorted(set(perms))
        bind.execute(
            sa.update(role).where(role.c.id == row.id).values(permissions=perms)
        )


def _revoke_permission() -> None:
    bind = op.get_bind()
    role = sa.table(
        "role",
        sa.column("id", _uuid()),
        sa.column("name", sa.String()),
        sa.column("permissions", sa.JSON()),
    )
    rows = bind.execute(
        sa.select(role.c.id, role.c.name, role.c.permissions).where(
            role.c.name.in_(_ROLES_TO_GRANT)
        )
    ).fetchall()
    for row in rows:
        perms = _as_list(row.permissions)
        if _PERMISSION not in perms:
            continue
        perms = [p for p in perms if p != _PERMISSION]
        bind.execute(
            sa.update(role).where(role.c.id == row.id).values(permissions=perms)
        )


def _as_list(value: object) -> list[str]:
    """Normalise a stored permissions column (JSON array, or a JSON string) to a list."""
    if value is None:
        return []
    if isinstance(value, list):
        return list(value)
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return list(parsed) if isinstance(parsed, list) else []
    return []


def downgrade() -> None:
    _revoke_permission()
    op.drop_index(
        "ix_interview_assignment_interviewer_id", table_name="interview_assignment"
    )
    op.drop_index("ix_interview_assignment_stage_id", table_name="interview_assignment")
    op.drop_index(
        "ix_interview_assignment_campaign_id", table_name="interview_assignment"
    )
    op.drop_index(
        "ix_interview_assignment_organisation_id", table_name="interview_assignment"
    )
    op.drop_table("interview_assignment")

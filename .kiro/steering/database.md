---
inclusion: always
---

# Database standards

## Conventions
- UUID primary keys.
- UTC timestamps; `created_at` and `updated_at` on all tables.
- `created_by` / `updated_by` where appropriate.
- Optimistic concurrency (`version` column) where concurrent edits matter.
- Check constraints, foreign keys, unique constraints.
- Indexes based on demonstrated query needs (not speculative).
- Soft deletion only where business + audit needs justify it.
- Immutable version records for approved JDs, rule-set versions, threshold versions, and
  screening runs.

## Immutability pattern
Approved versioned entities (JDVersion, RuleSetVersion, ThresholdVersion, ScreeningRun)
are append-only once approved/completed. Changes create a new version; the prior version
is retained and remains reproducible.

## Tenant / org scoping
Every scoped table carries an organisation key. Repositories and services must scope all
reads/writes by organisation (and by campaign for object-level authorisation) to prevent
data leakage.

## Migrations
- All schema changes via Alembic migrations. Never edit production schema manually.
- Migrations are reviewed and validated in CI before deployment.

## Prohibited
No dynamic SQL from user input. Parameterised access only.

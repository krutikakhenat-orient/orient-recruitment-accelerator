# Backup & Restore

> These procedures are documented and designed to be testable in a non-production
> environment before relying on them in production.

## What to back up
1. **PostgreSQL** — the system of record (campaigns, applications, immutable versions,
   screening runs, audit chain).
2. **Object storage** (resumes/JDs) — S3/MinIO bucket.
3. **Secrets** — managed in the secret store, backed up by that system (never in the DB
   backup).

## PostgreSQL backup (logical)

```bash
# Encrypted logical dump (pipe through your KMS/age/gpg of choice).
pg_dump --format=custom --no-owner "$ORA_DATABASE_URL" > ora_$(date +%F).dump
```

Store dumps encrypted at rest with restricted access. Retain per the organisation's policy.

## PostgreSQL restore (test procedure)

```bash
createdb ora_restore_test
pg_restore --no-owner --dbname=ora_restore_test ora_YYYY-MM-DD.dump
# Point a disposable app instance at ora_restore_test and run /ready + a smoke test.
```

## Object storage
Use the provider's versioned-bucket replication or `mc mirror` (MinIO client) to a backup
bucket. Restores copy objects back by their storage key; the DB holds the authoritative
key → document mapping.

## Audit-chain integrity after restore
After any restore, run the audit chain verification for each organisation
(`audit.service.verify_chain`) to confirm the append-only hash chain is intact. A broken
chain indicates tampering or an incomplete restore and must be investigated.

## Restore test cadence
Perform a full restore rehearsal into a disposable environment on a regular schedule and
record the result (duration, data completeness, audit-chain verification) as part of the
production readiness evidence.

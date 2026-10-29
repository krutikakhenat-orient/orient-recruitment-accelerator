# Administrator Guide

Audience: System Administrators and Recruitment Administrators operating Orient
Recruitment Accelerator.

## Initial setup
1. Deploy the stack (see `docs/deployment.md`) and run `alembic upgrade head`. Migration
   `0009_interview_assignment` creates the `interview_assignment` table and grants the new
   `interview.assign` permission to existing **Recruiter Admin** and **System Admin** roles
   (additive; no data reset). On an existing database you must run this migration for those
   roles to manage interviewer assignments.
2. Seed foundation data for local/demo use: `python -m app.cli.seed` (synthetic only;
   refuses to run in a production environment).
3. In production, create the first organisation and a System Administrator user through a
   controlled bootstrap (not the synthetic seed).

## Users & roles
- Roles are permission bundles (see `docs/permission-matrix.md`). Assign the least
  privilege needed.
- Assign recruiters and recruiter admins to specific campaigns — a permission only takes
  effect for a campaign the user is assigned to (object-level authorisation).
- **Interviewer assignment**: interview-panel members now see candidates only for the jobs
  (and, optionally, stages) they are **assigned** to. Manage assignments on a campaign's
  **Interviews** tab (Recruiter Admin, for campaigns it manages) or, organisation-wide, as
  System Administrator — both require the `interview.assign` permission. Assignment is
  metadata only and grants **no** candidate-content access; removing an assignment revokes
  worklist access on the next request and preserves any assessments already submitted.
- System administrators do **not** automatically see candidate content; any such access
  must be explicitly authorised and is logged. Holding `interview.assign` lets a System
  Administrator manage interviewer assignments without gaining candidate-content access.

## Governance controls
- **Rules**: a rule set must be approved by someone other than its creator.
- **Thresholds**: a change needs a reason and, when four-eyes is on, a distinct approver;
  each change creates a new immutable version with an audit event.
- **Campaign publication**: blocked until an approved JD, rule set, form, threshold, and a
  privacy-notice version are all present.

## Retention & privacy
- Configure retention policies per record category under the Privacy module.
- Every retention action (notify/restrict/delete/anonymise/legal-hold) is logged.
- Handle privacy requests (access/export, correction, deletion, restriction, consent
  withdrawal) through the Privacy endpoints; each has an auditable lifecycle.

## Monitoring
- Health: `GET /health`; readiness (incl. DB): `GET /ready`.
- Logs are structured JSON with correlation ids and no candidate PII.
- Audit trail is append-only; verify chain integrity after any restore.

## Production hardening reminders
Set a strong JWT secret and real CORS origins; wire a production malware scanner; enable
storage/DB encryption; enable SAST + container scanning in CI. See
`docs/security-checklist.md`.

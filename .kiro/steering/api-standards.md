---
inclusion: always
---

# API standards

## Versioning & grouping
All REST APIs live under `/api/v1/`. Groups: auth, organisations, users, roles,
permissions, projects, campaigns, job-descriptions, rules, forms, candidates,
applications, documents, screening, reviews, interviews, slots, assessments, decisions,
waitlists, talent-pool, notifications, reports, audit, privacy, administration.

## Request/response
- Pydantic request and response models. No direct ORM serialization.
- Consistent pagination (limit/offset or cursor), explicit filtering, safe sorting
  (whitelisted sort fields only).
- Consistent error envelope: `{ "error": { "code", "message", "correlation_id", "details"? } }`.
- Request correlation ID on every request/response and log line.

## Safety
- Idempotency keys for sensitive creation endpoints (campaigns, applications, screening runs,
  threshold changes, interview invitations).
- Optimistic concurrency via `version` / ETag on mutable resources.
- No PII in URL paths where avoidable.
- Server-side permission + object-level authorisation on every endpoint, independent of UI.
- Rate-limit strategy per endpoint class (public, authenticated, admin).

## Documentation
OpenAPI generated from FastAPI; each endpoint documents the required permission(s).

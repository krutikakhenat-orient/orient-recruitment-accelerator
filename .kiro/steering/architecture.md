---
inclusion: always
---

# Architecture

## Style

Modular monolith (see docs/adr/ADR-0001). A single FastAPI application composed of
bounded modules. Do **not** introduce microservices or Kubernetes unless a separate ADR
demonstrates a clear operational need.

## Bounded modules

Identity & Access, Organisations, Projects, Campaigns, Job Descriptions, Rules,
Candidates, Applications, Documents, Extraction, Screening, Human Review, Interviews,
Walk-in Slots, Assessments, Hiring Decisions, Waitlists, Talent Pool, Notifications,
Reporting, Privacy, Audit, System Administration.

## Layering (strict)

```
HTTP router  (thin: auth, validation, serialization only — NO business logic)
  -> application service   (orchestration, transaction boundaries)
    -> domain policy       (invariants, separation-of-duties, state guards)
      -> repository        (data access, tenant/campaign scoping)
        -> PostgreSQL
```

Rules:
- Controllers/routers must contain no business logic.
- ORM models (SQLAlchemy) are never serialized directly; map to Pydantic schemas.
- Modules communicate through service interfaces, not by reaching into each other's
  repositories or ORM models. Avoid circular dependencies. Use dependency injection.

## Mandatory choke points

- **Screening** always goes through the dedicated Screening Service. No ad-hoc scoring.
- **Application status changes** always go through the single Transition Service. Generic
  CRUD endpoints must never mutate status directly.
- **Audit** events are emitted for every sensitive action via a shared audit outbox.

## Cross-cutting infrastructure

- Background jobs: Dramatiq workers backed by Redis (ADR-0012). Used for document
  processing, extraction, notifications, retention jobs.
- Object storage: S3-compatible behind a storage abstraction (MinIO locally, ADR-0004).
  Files are only ever accessed through signed, short-lived links. No public bucket access.
- Optional LLM adapter: isolated behind a service interface, disabled by default, output
  schema-validated and advisory only, with a deterministic fallback (ADR-0005, responsible-ai.md).

## Runtime independence

The core workflow must run with the LLM adapter disabled and must not depend on Kiro at
runtime. Kiro is build-time tooling only.

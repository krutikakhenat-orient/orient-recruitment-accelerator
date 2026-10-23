# Architecture Decision Records — Index

ADR-0001 is a full record (modular monolith). The decisions below are recorded here in
condensed form; each can be expanded into its own file as it is revisited. All are
**Accepted** as of the MVP build unless noted.

| ADR | Decision | Rationale (summary) |
|---|---|---|
| 0001 | Modular monolith over microservices | See ADR-0001-modular-monolith.md. Strong consistency, simpler ops; boundaries kept extractable. |
| 0002 | FastAPI | Typed, async-capable, Pydantic-native, OpenAPI out of the box. |
| 0003 | PostgreSQL | Relational integrity, JSONB for rule/answer blobs, mature ops. |
| 0004 | Object-storage abstraction | `ObjectStore` interface; MinIO local, S3 later; files only via signed links. |
| 0005 | Deterministic rules engine (typed JSON DSL) | Rules are data, not code; no eval/exec; reproducible; LLM advisory-only. |
| 0006 | Candidate/Application separation | Master profile never rewrites per-campaign application answers. |
| 0007 | Immutable JD & rule-set versions | Approved versions frozen; changes create new versions; reproducibility + audit. |
| 0008 | Screening-result immutability | Each run append-only with version pointers + input hash + engine version. |
| 0009 | Human-approval controls | No auto-reject on score; no auto-invite by default; four-eyes thresholds; SoD on rules. |
| 0010 | Authentication strategy | Argon2id local creds + TOTP scaffold; OIDC/SAML behind an interface. |
| 0011 | Audit strategy | Append-only events with a per-organisation prev-hash chain (tamper-evident). |
| 0012 | Background-job framework | Dramatiq over Celery (simpler, typed) + Redis. Worker wiring is deferred until needed. |
| 0013 | OCR strategy | Tesseract fallback behind the extractor interface; reports unavailable when absent. |
| 0014 | Notification abstraction | Provider-neutral email adapter; MailHog local; template versioning + delivery logs. |
| 0015 | Talent-pool consent | Separate explicit opt-in distinct from application consent; withdrawable. |
| 0016 | Multi-tenancy deferral | Single-org MVP; organisation key carried on every table so SaaS isolation can be added. |

## Open decisions (see docs/open-decisions.md)
Field-level encryption mechanism; audit tamper-evidence upgrade (WORM); re-evaluation
approval granularity; first SSO protocol; production OCR licensing posture.

# Implementation Plan — Orient Recruitment Accelerator

Test-first where practical. Each task references the requirement IDs it satisfies.
Implementation does not begin until requirements.md, design.md, and tasks.md are consistent
(this plan is the final gate artifact). Tasks are grouped by the seven phases.

---

## Phase 0 — Specification & governance artifacts (no app code)

- [ ] 0.1 Write Architecture Decision Records in docs/adr/ for: modular monolith vs
  microservices (0001), FastAPI (0002), PostgreSQL (0003), object-storage abstraction
  (0004), rules-engine approach (0005), candidate/application separation (0006), immutable
  JD & rule versions (0007), screening-result immutability (0008), human-approval controls
  (0009), authentication strategy (0010), audit strategy (0011), background-job framework
  (0012), OCR strategy (0013), notification abstraction (0014), talent-pool consent (0015),
  multi-tenancy deferral (0016).
  - _Requirements: Assumptions & Open Decisions_
- [ ] 0.2 Write docs/threat-model.md (STRIDE + OWASP + domain threats). _Req 16.1_
- [ ] 0.3 Write docs/permission-matrix.md (role x permission x object-scope). _Req 1.2, 1.3_
- [ ] 0.4 Write docs/state-machines.md (full campaign + application transition tables). _Req 2.3_
- [ ] 0.5 Write docs/security-checklist.md and docs/privacy-checklist.md. _Req 16.1, 14.*_

## Phase 1 — Foundation

- [x] 1.1 Scaffold repository per structure.md (backend, frontend, deploy, seed, docs, CI).
  - _Requirements: steering/structure.md_
- [x] 1.2 docker-compose with PostgreSQL, Redis, MinIO, MailHog, reverse proxy; .env.example;
  startup environment validation; /health and /ready endpoints.
  - _Requirements: 16.2, 16.3; steering/devsecops.md_
- [x] 1.3 FastAPI app skeleton: core (config, logging with correlation id and PII-safe
  filters, error envelope), db session/base/mixins, module package layout.
  - _Requirements: steering/architecture.md, api-standards.md, coding-standards.md_
- [x] 1.4 React + Vite + TS strict skeleton with router, TanStack Query, portal shells, and
  accessible component base. (tsc strict + vitest green)
  - _Requirements: steering/accessibility.md, technology.md_
- [x] 1.5 Identity & Access: user model, Argon2id hashing, token issue/refresh, session
  cookie flags + CSRF, auth-provider interface, TOTP MFA scaffold. Tests first.
  - _Requirements: 1.1_
- [x] 1.6 RBAC: permission + role tables, effective-permission resolver, permission
  dependency, object-level authz helper. Permission tests.
  - _Requirements: 1.2, 1.3_
- [x] 1.7 Audit foundation: append-only AuditEvent model + per-org hash chain, PII
  exclusion. Audit-event tests. (Transactional outbox deferred to when cross-module
  events need async dispatch; current events are written in-transaction.)
  - _Requirements: 13.1_
- [x] 1.8 Alembic baseline migration + migration consistency tests.
  - _Requirements: steering/database.md_
- [x] 1.9 CI pipeline (format, lint, type-check, unit, integration, frontend, dependency
  scan, secret scan, migration validation, build). SAST + container-scan + a11y-axe steps
  are stubbed with notes to enable as images/codebase stabilise.
  - _Requirements: steering/devsecops.md_

## Phase 2 — Campaign & JD

- [x] 2.1 Organisations + Projects modules (model, service, policy, repo, schemas, router).
  - _Requirements: 2.1_
- [x] 2.2 Campaigns module with TransitionService and campaign state machine; reject invalid
  transitions; publication gating. State-transition tests. (AC-01, AC-04 verified)
  - _Requirements: 2.2, 2.3, 2.4 (AC-01, AC-04)_
- [x] 2.3 Documents module: upload intake, extension+MIME+signature+size validation, hashing,
  duplicate detection, safe filename, quarantine, malware-scan adapter. Document-validation +
  security tests (malicious file, invalid MIME, signature mismatch, EICAR). Signed download
  links deferred to Phase 3 when candidate downloads are introduced.
  - _Requirements: 3.1, 16.1 (AC-19)_
- [x] 2.4 Extraction module: JD parser adapters (PDF via PyMuPDF when present, DOCX, TXT;
  OCR fallback reports unavailable without Tesseract), structured draft, evidence spans,
  confidence. Non-LLM baseline.
  - _Requirements: 3.2_
- [x] 2.5 Job Descriptions module: JD upload/review API, approve -> immutable JDVersion,
  re-version flow (new draft cloned from approved; original preserved). JD immutability tests.
  Linking a new rule version happens in Phase 4 when rules exist.
  - _Requirements: 3.3 (AC-02)_
- [x] 2.6 Dynamic form schema: FormSchema/FormVersion/FormField, excluded-field enforcement,
  compensation default-off, accessibility-assistance (non-scoring). Form tests.
  - _Requirements: 4.1_

## Phase 3 — Candidate application

- [x] 3.1 Candidates module: canonical candidate, consent state (separate talent-pool
  opt-in + withdrawal, AC-16), duplicate link history.
  - _Requirements: 5.2_
- [x] 3.2 Public application endpoint (unauthenticated) with strict answer validation,
  mandatory privacy consent + separate talent-pool opt-in. Candidate-facing React page is
  deferred to the frontend-portals pass; the API + validation are complete and tested.
  - _Requirements: 5.1 (AC-05)_
- [x] 3.3 Applications module: per-campaign application, snapshotted answers (verified no
  overwrite on profile change), disposition via application TransitionService.
  - _Requirements: 5.2_
- [x] 3.4 Resume processing: validate + quarantine + scan (reused Documents pipeline),
  type-detect, text extract, parse fields with span + confidence, compare vs entered, flag
  conflicts/low-confidence/safety-flags, verified/unverified stored separately. Security
  tests incl. prompt-injection + keyword-stuffing + hidden-text flagging.
  - _Requirements: 5.3 (AC-06, AC-07)_
- [x] 3.5 Candidate confirmation/correction API (verify/correct extracted fields, original
  preserved) + duplicate review flagging. UI deferred to the frontend-portals pass.
  - _Requirements: 5.3, 5.4_
- [x] 3.6 Skill taxonomy: Skill + SkillAlias, related-not-equivalent enforcement.
  - _Requirements: 6.1_

## Phase 4 — Rules & screening

- [x] 4.1 Rules engine: typed JSON DSL parser/validator (whitelisted node types + operators,
  reject malformed at validation time) and deterministic evaluator. Determinism tests.
  - _Requirements: 7.1_
- [x] 4.2 Rules module: rule authoring, SoD (creator != sole approver), approval -> immutable
  RuleSetVersion; ThresholdSet/ThresholdVersion with threshold.change permission + reason +
  four-eyes + audit. Authz + versioning tests.
  - _Requirements: 7.2 (AC-03, AC-11, AC-12)_
- [x] 4.3 Screening service: validation -> eligibility gates -> weighted score -> confidence
  -> review triggers -> recommendation; immutable ScreeningRun + CriterionResults with all
  version pointers + input hash + engine version; uses only approved versions.
  Rules-regression tests (identical inputs=identical result; old results reproducible).
  - _Requirements: 8.1, 8.2 (AC-08, AC-10)_
- [x] 4.4 Explainable score API: per-criterion evidence, source, confidence, awarded/max,
  reason (CriterionResultRead). Override + approver fields deferred to the override flow.
  - _Requirements: 8.3 (AC-09)_
- [x] 4.5 Human Review queue + reviewer actions + ReviewAction correction records (original
  preserved). Human-review tests.
  - _Requirements: 9.1_

## Phase 5 — Interview workflow

- [x] 5.1 Interviews module: interview approval (interview.approve) gating; no auto-invite by
  default. Approval tests.
  - _Requirements: 10.1 (AC-14)_
- [x] 5.2 Walk-in Slots: stages, slots, capacity, location, mode, panel assignment,
  invitation status, candidate confirmation, attendance/no-show; capacity guard enforced.
  Reschedule modelled via invitation status; dedicated reschedule flow is a follow-up.
  - _Requirements: 10.2_
- [x] 5.3 Assessments module: structured assessment forms, conflict declaration; no
  prohibited inference features.
  - _Requirements: 10.3_
- [x] 5.4 Hiring Decisions: select/reject/hold/withdraw via application TransitionService
  with approve/recommend permission split.
  - _Requirements: 10.4_
- [ ] 5.5 Notifications module: provider-neutral adapter, template versioning, delivery/failure
  tracking; no internal scores in candidate comms. (DEFERRED — candidate-communication-impact
  is already flagged on every relevant transition; the delivery adapter + logs are a
  follow-up. Candidate comms already exclude internal scores by design.)
  - _Requirements: 12.1 (AC-15)_

## Phase 6 — Waitlist & talent pool

- [x] 6.1 Waitlists module (application, campaign, reason, screening version, eligibility,
  expiry, comms status).
  - _Requirements: 11.1_
- [x] 6.2 Controlled re-evaluation: permitted triggers only; preserves original run; creates
  a new run; records initiator + reason; reports old-vs-new change. Re-evaluation tests.
  - _Requirements: 11.2 (AC-13)_
- [x] 6.3 Talent Pool module: consent-gated search; matches are advisory (verify evidence
  before contact); consent withdrawal in candidates module. Access audited.
  - _Requirements: 11.3 (AC-16)_

## Phase 7 — Governance & production hardening

- [x] 7.1 Privacy module: privacy requests (access/export, correction, deletion, restriction,
  consent-withdrawal) with auditable lifecycle. Privacy-workflow tests.
  - _Requirements: 14.1_
- [x] 7.2 Retention: configurable policies per category; actions notify/restrict/delete/
  anonymise/legal-hold; every action logged. Retention tests.
  - _Requirements: 14.2 (AC-17)_
- [x] 7.3 Reporting: HR dashboard + management dashboard with small-group suppression; no
  misleading individual rankings. Dashboard tests.
  - _Requirements: 15.1, 15.2_
- [x] 7.4 Security hardening: object-level authz (tested), security headers + HSTS, restricted
  CORS, lockout, upload signature/MIME/zip-bomb defences, prohibited-field enforcement,
  prompt-injection flagging. Egress allow-list + CSV-export neutralisation remain follow-ups
  (noted in security-checklist.md).
  - _Requirements: 16.1 (AC-18, AC-19)_
- [x] 7.5 Observability: structured PII-safe logs with correlation ids; health/readiness
  endpoints. Metrics/tracing exporters are a deployment follow-up.
  - _Requirements: steering/devsecops.md_
- [x] 7.6 Synthetic resume generator (clear match, non-match, borderline, missing dates,
  conflicting form/resume, scanned, multi-column, keyword-stuffed, hidden-instruction attempt,
  malicious filename, duplicate, cross-campaign match) — all marked synthetic; no real names.
  - _Requirements: 16.4 (AC-21)_
- [x] 7.7 Docs: ADR index, threat model, permission matrix, state machines, security + privacy
  checklists, deployment (clean-env bootstrap), backup/restore (testable), admin + HR guides,
  candidate privacy flow, open-decisions register.
  - _Requirements: 16.3 (AC-24, AC-25)_
- [~] 7.8 End-to-end coverage: 115 backend tests cover the lifecycle and the AI-disabled path
  (deterministic engine is authoritative). A single black-box e2e harness over the running
  stack and an explicit per-AC assertion sweep are a follow-up.
  - _Requirements: all (AC-20, AC-22, AC-23)_

---

## Acceptance-criteria coverage map

| AC | Covered by task(s) |
|---|---|
| AC-01 | 2.1, 2.2 |
| AC-02 | 2.5 |
| AC-03 | 4.2 |
| AC-04 | 2.2 |
| AC-05 | 3.2 |
| AC-06 | 3.4 |
| AC-07 | 3.4, 3.5 |
| AC-08 | 4.3 |
| AC-09 | 4.4 |
| AC-10 | 4.3, 4.5 |
| AC-11 | 4.2 |
| AC-12 | 4.2 |
| AC-13 | 6.2 |
| AC-14 | 5.1 |
| AC-15 | 5.5 |
| AC-16 | 6.3 |
| AC-17 | 7.2 |
| AC-18 | 7.4, 1.6 |
| AC-19 | 2.3, 3.4, 7.4 |
| AC-20 | 7.8 |
| AC-21 | 7.6 |
| AC-22 | 7.8, 1.2 |
| AC-23 | 1.7, 7.8 |
| AC-24 | 7.7, 1.2 |
| AC-25 | 7.7 |

# Orient Recruitment Accelerator — Project Documentation

Version: 1.0 · Status: all 7 build phases implemented · Last reviewed against source on
2026-10-08.

A production-quality, secure, and **explainable** recruitment campaign management and
candidate screening platform. AI may extract, normalise, summarise and recommend — it
**never** makes the final hiring decision. Mandatory eligibility and weighted scoring use
deterministic, version-controlled rules; every score is reproducible and evidence-backed.
The system runs fully without any LLM service.

> All example accounts, credentials, and data in this document are **synthetic** and for
> local evaluation only. The product is not claimed to be automatically legally compliant
> and is not claimed to be risk-free.

---

## Table of contents

1. [Overview](#1-overview)
2. [Core principles](#2-core-principles)
3. [Architecture](#3-architecture)
4. [Technology stack](#4-technology-stack)
5. [Repository layout](#5-repository-layout)
6. [Domain model & glossary](#6-domain-model--glossary)
7. [Roles & permissions](#7-roles--permissions)
8. [Campaign lifecycle](#8-campaign-lifecycle)
9. [Running locally](#9-running-locally)
10. [Using the app (by role)](#10-using-the-app-by-role)
11. [API reference](#11-api-reference)
12. [Configuration](#12-configuration)
13. [Security & privacy](#13-security--privacy)
14. [Testing & quality gates](#14-testing--quality-gates)
15. [Known gaps & dev-only helpers](#15-known-gaps--dev-only-helpers)
16. [Related documents](#16-related-documents)

---

## 1. Overview

The platform runs the full recruitment lifecycle for an organisation:

- **Projects & campaigns** — organise hiring into projects, each with one or more campaigns
  (a specific role to fill). Campaigns move through a controlled lifecycle state machine.
- **Job descriptions** — uploaded and stored as **immutable, approved versions**.
- **Application forms** — versioned, approved schemas defining the candidate questions.
- **Rules & thresholds** — a typed-JSON rules DSL (no `eval`/`exec`) defines mandatory
  eligibility and weighted scoring. Rule-set versions are immutable and require four-eyes
  approval; thresholds are versioned with a reason.
- **Public application** — candidates apply through an unauthenticated page, submitting
  answers and a resume. Consent and duplicate detection happen on intake.
- **Extraction** — resume data is extracted into fields staff can review and correct.
- **Screening** — deterministic, reproducible runs score each application against the
  approved rule-set and threshold. Runs are immutable and explainable. Screening **never
  auto-rejects**; borderline/low-confidence cases route to human review.
- **Review queue** — reviewers advance, hold, request info, waitlist, or escalate.
- **Interviews** — stages, slots, invitations (approved via four-eyes). Recruiters schedule;
  the Interview Panel confirms **attendance** from its own dashboard.
- **Assessments & decisions** — the panel confirms attendance and submits assessments; final
  select/reject requires approval authority (Recruiter Admin).
- **Waitlist** — candidates can be waitlisted and the list re-evaluated.
- **Talent pool** — searchable by skill, with candidate-controlled withdrawal.
- **Privacy & retention** — data subject requests and retention policies.
- **Reporting & audit** — HR and management dashboards, plus a hash-chained audit log.

## 2. Core principles

These are binding product rules (see `.kiro/steering/product.md`):

1. AI may extract, normalise, summarise and recommend — never the final hiring decision.
2. No candidate rejection based solely on an LLM output.
3. Mandatory eligibility and weighted scoring are deterministic and version-controlled.
4. Every score is reproducible from stored inputs plus the stored rule version.
5. Every score component identifies its underlying candidate evidence.
6. Missing evidence is not proof of absence — it routes to human review.
7. Low-confidence and conflicting data route to human review.
8. Threshold changes require an authorised approval and a reason.
9. Re-evaluation creates a **new** result and never overwrites the original.
10. Protected, medical and highly personal characteristics never influence screening.
11. Access follows least privilege with **object-level authorisation**.
12. The product runs fully without an LLM service.

## 3. Architecture

A **modular monolith** (ADR-0001): one deployable FastAPI application composed of
independent modules under `backend/app/modules/`, each owning its own router, service,
policy, repository, schemas and models.

```
Browser ─► Frontend (React + Vite, :5173)
             proxies /api/* ─────────────┐
                                          ▼
          Backend (FastAPI, :8000)
            router (thin)  →  service  →  policy  →  repository  →  DB
            rules_engine (typed-JSON DSL, deterministic evaluator, no eval)
            audit (append-only, hash-chained events)
                                          ▼
          Datastore: PostgreSQL (prod) / SQLite (local dev)
```

Strict layering:

```
HTTP router  (auth, validation, serialization only — NO business logic)
  -> application service   (orchestration, transaction boundaries)
    -> domain policy       (invariants, separation-of-duties, state guards)
      -> repository         (data access, tenant/campaign scoping)
        -> database
```

Mandatory choke points:

- **Screening** always goes through the Screening Service — no ad-hoc scoring.
- **Campaign status changes** always go through the single Transition Service.
- **Audit** events are emitted for every sensitive action.

## 4. Technology stack

| Layer      | Technology                                                            |
|------------|-----------------------------------------------------------------------|
| Backend    | Python 3.13 (3.12 target), FastAPI, SQLAlchemy 2.x, Pydantic v2, Alembic |
| Jobs       | Dramatiq (worker wiring deferred; ADR-0012)                           |
| Datastore  | PostgreSQL (production), SQLite (local, dependency-free)               |
| Auth       | JWT (HS256) access + refresh, Argon2id hashing, TOTP scaffold          |
| Frontend   | React 18, TypeScript (strict), Vite 6, React Query, React Router, React Hook Form, Zod |
| Tests      | pytest (backend), Vitest + Testing Library (frontend)                 |
| Lint/Types | ruff + mypy (strict) backend; eslint + tsc (strict) frontend          |

## 5. Repository layout

```
backend/     FastAPI modular monolith
  app/
    core/          config, logging, errors, security, correlation
    db/            SQLAlchemy base, session, model registry
    api/           shared dependencies (auth actor, db session, settings)
    rules_engine/  typed-JSON DSL + deterministic evaluator
    modules/       one folder per bounded context
    cli/           synthetic seed script
    main.py        app factory, middleware, router registration
  alembic/         ordered migrations
  tests/           pytest suite
  run_local.py     zero-dependency SQLite runner
frontend/    React + TypeScript (Vite)
  src/
    api/           typed client, auth, resource wrappers
    app/           router, layout, auth context
    components/    UI kit, toast, Orient HR Assistance
    pages/         one page per portal area
deploy/      docker-compose, reverse proxy, env template
seed/        synthetic data
docs/        this file, the docs hub, ADRs, guides, checklists
.kiro/       steering rules + spec (requirements, design, tasks)
```

Each backend module follows: `router.py` (thin HTTP), `service.py` (orchestration),
`policy.py` (invariants/SoD), `repository.py` (data access), `models.py` (ORM),
`schemas.py` (Pydantic).

## 6. Domain model & glossary

- **Organisation** — tenant boundary. MVP is single-org; the key is carried everywhere.
- **Project** — an approved hiring need.
- **Campaign** — one position-hiring effort within a project. The main working unit.
- **JD Version** — an immutable, approved version of a campaign's job description.
- **Rule-Set Version** — an immutable, approved set of typed-JSON screening criteria.
- **Threshold Version** — an immutable, approved pair of score cut-offs (review-below,
  recommend-at-or-above).
- **Form Version** — an immutable, approved application-form schema.
- **Application** — one candidate's submission to a campaign (one per candidate per
  campaign).
- **Extracted Field** — a value pulled from a resume, pending human verification.
- **Screening Run** — an immutable, reproducible scoring result with per-criterion
  evidence.
- **Review Item** — a flagged case routed to a human by a screening run.
- **Interview Stage / Slot / Invitation** — interview scheduling entities.
- **Decision** — a final select/reject/hold outcome for an application.

Immutable, append-only once approved/completed: JDVersion, RuleSetVersion,
ThresholdVersion, FormVersion, ScreeningRun. Changes create a new version; prior versions
remain reproducible.

## 7. Roles & permissions

Three operational roles plus four governance/public roles. Seed accounts: email
`synthetic.<role>@example.com`, password `SyntheticDevPassword123`.

| Role | What it can do |
|---|---|
| Recruiter | Create projects/campaigns; author JD/rules; **run screening**; review applications; schedule interviews; manage waitlist. The authoring side of four-eyes. |
| Recruiter Admin | Everything the Recruiter does **plus** all approvals/sign-off: **approve** JD, rules, thresholds, interviews, and final hiring decisions; correct candidate data; audited PII reveal. Does **not** hold system administration. |
| Interview Panel | Confirm interview **attendance** and submit structured assessments for candidates they interview. |
| Management Viewer | Aggregated dashboards only; no candidate PII |
| Audit Viewer | Read-only audit log |
| System Admin | Manage users, system config, privacy requests. No automatic candidate-content access. |
| Candidate | Not a staff user; applies via the public page |

> The former **HR Head** and **Hiring Manager** roles were consolidated into **Recruiter
> Admin**; the standalone **Recruitment Admin** role was merged into the same tier. There is
> no longer a `synthetic.hr_head`, `synthetic.hiring_manager`, or
> `synthetic.recruitment_admin` account — use `synthetic.recruiter_admin@example.com`.

Two authorisation layers apply to every protected action:

1. **Permission** (role-level) — does the role hold the required permission?
2. **Object-level assignment** — is the actor assigned to the specific campaign?

The campaign creator is auto-assigned. Others are added via the campaign's **Team access**
card or `POST /api/v1/campaigns/{id}/assignments`. **Separation of duties:** the creator of
a rule-set or threshold cannot be its approver (four-eyes).

Full matrix: [permission-matrix.md](permission-matrix.md).

## 8. Campaign lifecycle

Enforced by the Transition Service; any transition not in the table is rejected (HTTP 409).

```
draft → jd_uploaded → jd_review → criteria_configuration → criteria_review
  → approval_pending → approved → published → applications_open
  → applications_closed → screening → human_review → interview_planning
  → interviewing → selection_review → completed → closed → archived
```

| Transition | Permission | Prerequisite |
|---|---|---|
| draft → jd_uploaded | jd.upload | validated JD document |
| jd_uploaded → jd_review | jd.review | extracted JD draft |
| jd_review → criteria_configuration | jd.approve | approved JD version |
| criteria_configuration → criteria_review | rule.create | rule-set draft |
| criteria_review → approval_pending | rule.approve | approved rule-set version |
| approval_pending → approved | campaign.approve | all 5 artifacts approved |
| approved → published | campaign.publish | all 5 artifacts approved |
| published → applications_open | campaign.publish | — |

The "5 artifacts" are: approved JD, approved rule-set, approved form, active threshold, and
a privacy notice. Pause/resume and cancellation (from early states) are also supported.
Full tables: [state-machines.md](state-machines.md).

## 9. Running locally

### 9a. Zero-dependency run (recommended for evaluation)

Prerequisites: Python 3.13 and Node.js. No Docker/PostgreSQL needed.

**Backend** (SQLite, auto-creates schema, seeds synthetic data, serves :8000):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe run_local.py
```

API at http://localhost:8000, interactive docs at http://localhost:8000/docs.

**Frontend** (dev server, proxies `/api` → :8000, serves :5173):

```powershell
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in with a seed account (section 7). On Windows, if
`npm run dev` is blocked by execution policy, run Vite directly:
`node node_modules\vite\bin\vite.js --host --port 5173`.

### 9b. Full Docker stack

Prerequisites: Docker + Docker Compose.

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml up --build
```

Brings up API, PostgreSQL, Redis, MinIO (object storage), and MailHog (email sandbox).
See [deployment.md](deployment.md).

## 10. Using the app (by role)

Opening a campaign properly spans multiple roles (separation of duties). The realistic
flow:

1. **Recruiter** — create a Project, then a Campaign (auto-assigned). On the campaign tabs:
   upload a JD (Job Description tab) and create the form (Form tab). Scoring criteria and the
   default 50% threshold are generated automatically from the JD on approval — there is no
   separate Rules tab. Assign the Recruiter Admin via the **Team access** card so a different
   user can approve.
2. **Recruiter Admin** — approve the JD (which auto-generates + approves JD-derived criteria
   and the 50% threshold), approve the form, then use the Overview lifecycle buttons:
   Approve campaign → Publish → Open applications.
3. **Candidate** — open the campaign's apply link (Overview → **Copy public link** or scan
   the auto-generated **QR code**), submit the form with a resume (fields pre-fill from the
   resume; every value stays editable). No login. On submit they see a single confirmation:
   "Thank you for your application".
4. **Recruiter** — campaign → **Applications & Screening** tab → **Run screening** on an
   applicant. Each row shows the **Resume Score**, a **View form** button (shows the
   candidate's submitted answers), and a review status. Clean candidates scoring ≥50% are
   placed on the Interview Panel automatically; below-50/flagged candidates go to the Review
   Queue.
5. **Recruiter / Recruiter Admin** — **Review Queue** → select the campaign → act on
   each item (Recommend interview / Waitlist / Request info / Escalate) with a reason.
6. **Recruiter / Recruiter Admin** — ≥50% candidates are already on the Interview Panel;
   to add a below-50 (under-review) candidate, use **Select for interview** (requires a
   recorded reason — a screening override, audited). Schedule slots as needed.
7. **Interview Panel** — from **My Assigned Interviews**: confirm **attendance**, then
   submit assessments. Attendance is the panel's responsibility, not the recruiter's.
8. **Recruiter Admin** — record the final hiring decision (select/reject need approval
   authority).
9. **Management Viewer / Audit Viewer** — dashboards and the audit log.

**Fast local shortcut:** each campaign's Overview tab has **"Open this campaign now (dev)"**
which creates and approves all five artifacts and opens the campaign in one click (dev-only;
disabled in production). A ready-made demo campaign ("DEMO - Senior Python Engineer") with
screened applicants and open review items is seeded for exploration.

Role-aware UI: tabs show a 🔒 when read-only for your role, and actions you cannot perform
are disabled with a short reason. Full walkthrough: [hr-guide.md](hr-guide.md).

## 11. API reference

All endpoints are under `/api/v1`. Authenticated calls require
`Authorization: Bearer <access_token>`. Errors use a typed envelope:
`{ "error": { "code", "message", "correlation_id", "details"? } }`. The authoritative,
always-current reference is the OpenAPI UI at http://localhost:8000/docs (non-production).

Health probes (unversioned): `GET /health`, `GET /ready`.

| Group | Method & path | Purpose |
|---|---|---|
| Identity | POST `/auth/login` | Email+password → token pair |
| Identity | POST `/auth/refresh` | Refresh token → new pair |
| Identity | GET `/auth/me` | Current actor, roles, permissions, assignments |
| Identity | POST `/users` | Create staff user (system_admin) |
| Projects | POST / GET `/projects`; GET `/projects/{id}` | Create / list / get |
| Campaigns | POST / GET `/campaigns`; GET `/campaigns/{id}` | Create / list / get |
| Campaigns | POST `/campaigns/{id}/transition` | Drive the lifecycle |
| Campaigns | POST `/campaigns/{id}/fast-track-open` | Drive an artifact-ready campaign straight to open |
| Campaigns | POST `/campaigns/{id}/assignments` | Assign a user (or self) to a campaign |
| Campaigns | DELETE `/campaigns/{id}` | Hard-delete a campaign + its data (campaign.edit, audited) |
| Job descriptions | POST `/job-descriptions/upload` | Upload → draft version |
| Job descriptions | PATCH `/job-descriptions/versions/{id}` | Edit a draft |
| Job descriptions | POST `/job-descriptions/versions/{id}/approve` | Approve (immutable) |
| Job descriptions | POST `/job-descriptions/versions/{id}/revise` | Revise → new version |
| Forms | POST `/forms/drafts`; POST `/forms/versions/{id}/approve` | Create / approve |
| Rules | POST `/rules/rule-sets/versions`; POST `/rules/rule-sets/versions/{id}/approve` | Create / approve (four-eyes) |
| Rules | POST `/rules/rule-sets/versions/from-jd` | Generate a tiered scoring rule-set from the approved JD |
| Rules | POST `/rules/rule-sets/versions/{id}/reject`; GET `/rules/rule-sets/versions/pending` | Reject a draft / list drafts awaiting approval |
| Rules | POST `/rules/thresholds/change` | Change threshold (versioned, four-eyes) |
| Public apply | GET `/public/open-roles` | Unauthenticated list of open roles (careers dropdown) |
| Public apply | GET `/public/campaigns/{id}/form` | Approved form for an open role |
| Public apply | POST `/public/campaigns/{id}/apply` | Unauthenticated candidate submission (multipart) |
| Applications | POST `/applications/walk-in-intake` | Bulk-ingest walk-in resumes (consent attested) |
| Applications | GET `/applications?campaign_id=...` | List a campaign's applications |
| Applications | GET `/applications/{id}` | Get one application |
| Applications | GET `/applications/{id}/extracted-fields` | List extracted resume fields |
| Applications | POST `/applications/{id}/extracted-fields/{fieldId}/verify` | Verify/correct a field |
| Candidates | GET `/candidates/{id}` | Get a candidate (contact PII masked) |
| Candidates | GET `/candidates/{id}/contact` | Reveal unmasked contact PII (candidate.view_pii, audited) |
| Candidates | POST `/candidates/{id}/talent-pool/withdraw` | Withdraw consent (204) |
| Screening | POST `/screening/applications/{id}/run` | Run deterministic screening |
| Screening | GET `/screening/applications/{id}/runs` | List immutable runs |
| Reviews | GET `/reviews?campaign_id=...` | List open review items |
| Reviews | POST `/reviews/{id}/actions` | Record a reviewer action |
| Interviews | POST `/interviews/stages` | Create a stage |
| Interviews | POST `/interviews/slots` | Create a slot |
| Interviews | POST `/interviews/invitations/approve` | Approve an invitation |
| Interviews | POST `/interviews/invitations/{id}/assign-slot` | Assign a slot |
| Interviews | POST `/interviews/invitations/{id}/attendance` | Record attendance (Interview Panel) |
| Assessments | GET `/assessments/panel` | Interview Panel dashboard (to-attend / to-assess / completed) |
| Assessments | GET `/assessments/assignable` | Candidates awaiting this panel member's assessment |
| Assessments | POST `/assessments` | Submit an assessment |
| Decisions | GET `/decisions/pending`; GET `/decisions/outcomes` | Assessed-awaiting-decision / decided candidates |
| Decisions | POST `/decisions` | Record a hiring decision |
| Waitlist | POST `/waitlist`; POST `/waitlist/reevaluate` | Add / re-evaluate |
| Talent pool | GET `/talent-pool/search?skill=...` | Search by skill |
| Privacy | POST `/privacy/requests`; POST `/privacy/requests/{id}/complete` | DSAR workflow |
| Privacy | POST `/privacy/retention-policies` | Set a retention policy |
| Reports | GET `/reports/hr-dashboard`; GET `/reports/management-dashboard` | Dashboards |
| Audit | GET `/audit` | List hash-chained audit events |
| Dev (local only) | POST `/dev/campaigns/{id}/open-now` | Create+approve all artifacts and open the campaign |

A copy-pasteable, call-by-call walkthrough is in [api-reference.md](api-reference.md).

## 12. Configuration

Backend settings are environment-driven with the prefix `ORA_` (optionally from a `.env`
file in local dev). Defaults live in `backend/app/core/config.py`.

| Variable | Default | Notes |
|---|---|---|
| `ORA_ENVIRONMENT` | `development` | `development` / `test` / `staging` / `production` |
| `ORA_DATABASE_URL` | `postgresql+psycopg://ora:ora@localhost:5432/ora` | SQLite accepted in dev only |
| `ORA_JWT_SECRET` | dev-only sentinel | Must be ≥32 chars & non-default in prod |
| `ORA_ACCESS_TOKEN_TTL_SECONDS` | `900` | 15-minute access token |
| `ORA_REFRESH_TOKEN_TTL_SECONDS` | `1209600` | 14 days |
| `ORA_MAX_FAILED_LOGINS` | `5` | Account lockout threshold |
| `ORA_LOCKOUT_SECONDS` | `900` | 15 minutes |
| `ORA_CORS_ALLOWED_ORIGINS` | `http://localhost:5173` | Comma-separated; no localhost in prod |
| `ORA_LLM_ADAPTER_ENABLED` | `false` | AI is advisory-only and off by default |

**Production safety:** on startup in staging/production the app refuses to boot if the JWT
secret is weak/default, if CORS allows localhost, or if the database URL is SQLite. The
dev-only router (`/api/v1/dev/*`) is not registered in production-like environments.

## 13. Security & privacy

- **AuthN:** JWT access + refresh; Argon2id hashing; account lockout; TOTP scaffold. Tokens
  are held in memory only on the frontend (never localStorage).
- **AuthZ:** fine-grained permissions + object-level campaign assignment on every protected
  endpoint, server-side and authoritative regardless of UI.
- **Separation of duties / four-eyes:** rule-set and threshold approval, and select/reject
  decisions, require an approver distinct from the author.
- **File upload safety:** extension + MIME + signature validation, size limits, quarantine
  before processing, malware-scan adapter, hash + duplicate detection, no execution of
  untrusted content.
- **Documents as untrusted data:** resumes/JDs never override system instructions; defences
  against prompt injection, hidden text, keyword stuffing.
- **Explainability:** screening is deterministic and reproducible; every score is
  evidence-backed; the system never auto-rejects and never requires an LLM.
- **Audit:** append-only, hash-chained events provide tamper evidence.
- **Privacy:** versioned consent, separate talent-pool opt-in, DSAR workflow, retention
  policies, candidate-controlled withdrawal. Protected/medical attributes never used in
  screening.

Deeper material: [threat-model.md](threat-model.md),
[security-checklist.md](security-checklist.md), [privacy-checklist.md](privacy-checklist.md),
[candidate-privacy-flow.md](candidate-privacy-flow.md).

## 14. Testing & quality gates

**Backend** (from `backend/`, venv active):

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest tests -q
```

**Frontend** (from `frontend/`):

```powershell
npm run typecheck
npm run lint
npm run test
```

Test strategy spans domain/unit, rules-engine, state-transition, permission, repository,
API-integration, document-validation, audit, privacy and retention tests on the backend;
component, form-validation, permission-state, accessibility and workflow tests on the
frontend; plus security tests (privilege escalation, IDOR, malicious upload, injection,
rate limiting, token expiry) and rules-regression proofs (identical inputs + rule version →
identical results; old results stay reproducible). All test/seed data is synthetic and
clearly marked. (See `.kiro/steering/testing.md`.)

## 15. Known gaps & dev-only helpers

Honest status of items that are intentionally local-only or not yet complete:

- **Dev "open now" endpoint** (`POST /api/v1/dev/campaigns/{id}/open-now`) and its Overview
  button are a local convenience; they relax four-eyes for thresholds and use a
  full-permission dev actor. Registered only outside production.
- **Interviews, assessments, decisions, waitlist, talent-pool and privacy** have complete
  backend endpoints; frontend coverage for some of these screens is partial (the core
  campaign/applications/screening/review flow is fully wired in the UI).
- Full WCAG conformance requires manual testing with assistive technologies and expert
  review; automated axe checks are necessary but not sufficient.

## 16. Related documents

| Document | Covers |
|---|---|
| [README.md](README.md) | Documentation hub / entry point |
| [api-reference.md](api-reference.md) | Full endpoint reference + worked example |
| [hr-guide.md](hr-guide.md) | Day-to-day usage + local walkthrough |
| [admin-guide.md](admin-guide.md) | System-admin operations |
| [state-machines.md](state-machines.md) | Campaign/application lifecycle |
| [permission-matrix.md](permission-matrix.md) | Role → permission mapping |
| [threat-model.md](threat-model.md) | Security analysis |
| [security-checklist.md](security-checklist.md) | Pre-release security checks |
| [privacy-checklist.md](privacy-checklist.md) | Privacy/retention checks |
| [candidate-privacy-flow.md](candidate-privacy-flow.md) | Candidate data & consent |
| [deployment.md](deployment.md) | Production deployment |
| [backup-restore.md](backup-restore.md) | Backup & restore |
| [open-decisions.md](open-decisions.md) | Deferred decisions |
| [adr/](adr/) | Architecture Decision Records |

---

_End of project documentation. All example data and credentials are synthetic and for local
evaluation only._

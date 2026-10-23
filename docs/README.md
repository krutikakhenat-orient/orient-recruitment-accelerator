# Orient Recruitment Accelerator — Documentation

A production-quality, secure, and **explainable** recruitment campaign management and
candidate screening platform. AI may extract, normalise, summarise and recommend — it
**never** makes the final hiring decision. Mandatory eligibility and weighted scoring use
deterministic, version-controlled rules; every score is reproducible and evidence-backed.
The system runs fully without any LLM service.

This folder is the documentation hub. Start here, then follow the links below.

> **Standard project reference:** [PROJECT_DOCUMENTATION.md](PROJECT_DOCUMENTATION.md) — a
> single comprehensive document covering overview, architecture, roles, lifecycle, running
> locally, API reference, configuration, security, and testing.

---

## Table of contents

1. [What the platform does](#1-what-the-platform-does)
2. [Architecture overview](#2-architecture-overview)
3. [Technology stack](#3-technology-stack)
4. [Repository layout](#4-repository-layout)
5. [Running locally](#5-running-locally)
6. [Seed accounts & roles](#6-seed-accounts--roles)
7. [The recruitment workflow end to end](#7-the-recruitment-workflow-end-to-end)
8. [API reference](#8-api-reference)
9. [Frontend](#9-frontend)
10. [Configuration](#10-configuration)
11. [Security & privacy model](#11-security--privacy-model)
12. [Testing & quality gates](#12-testing--quality-gates)
13. [Deployment](#13-deployment)
14. [Further reading](#14-further-reading)

---

## 1. What the platform does

The platform manages the full recruitment lifecycle for an organisation:

- **Projects & campaigns** — organise hiring into projects, each with one or more campaigns
  (a specific role to fill). Campaigns move through a controlled lifecycle state machine.
- **Job descriptions** — uploaded and stored as **immutable, approved versions**. Revisions
  create new versions; approved versions can never be edited in place.
- **Application forms** — versioned, approved schemas that define the questions candidates
  answer when applying.
- **Rules & thresholds** — a typed-JSON rules DSL (no `eval`/`exec`) defines mandatory
  eligibility and weighted scoring. Rule-set versions are immutable and require four-eyes
  approval; thresholds are versioned with a reason.
- **Public application** — candidates apply through an unauthenticated endpoint, submitting
  answers and a resume. Consent and duplicate detection are handled on intake.
- **Extraction** — resume data is extracted into fields that staff can **review and correct**
  (human-in-the-loop). Extraction is advisory only.
- **Screening** — deterministic, reproducible screening runs score each application against
  the approved rule-set and threshold. Runs are immutable and fully explainable. Screening
  **never auto-rejects**; it routes borderline/ineligible cases to human review.
- **Review queue** — reviewers advance, hold, or request more information on applications.
- **Interviews** — stages, time slots, invitations (approved via four-eyes), slot
  assignment, and attendance tracking.
- **Assessments & decisions** — panel members submit assessments; final select/reject
  decisions require approval authority (separation of duties).
- **Waitlist** — candidates can be waitlisted and the list re-evaluated when headcount frees
  up.
- **Talent pool** — searchable by skill, with candidate-controlled withdrawal (consent).
- **Privacy & retention** — data subject access/erasure requests and retention policies.
- **Reporting & audit** — HR and management dashboards, plus a hash-chained, tamper-evident
  audit log.

See [state-machines.md](state-machines.md) for the exact lifecycle transitions.

## 2. Architecture overview

The backend is a **modular monolith** (see [adr/](adr/)): one deployable FastAPI
application composed of independent modules under `backend/app/modules/`, each owning its
own router, service, repository, schemas and models. This was chosen over microservices for
strong consistency and MVP simplicity.

```
                 ┌─────────────────────────────────────────────┐
   Browser  ───► │  Frontend (React + Vite)  http://:5173        │
                 │   proxies /api/*  ──────────────┐             │
                 └─────────────────────────────────┼─────────────┘
                                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │  Backend (FastAPI)  http://:8000              │
                 │   api/deps  →  module routers  →  services     │
                 │   services  →  repositories  →  SQLAlchemy ORM │
                 │   rules_engine (typed-JSON DSL, no eval)       │
                 │   audit (hash-chained events)                  │
                 └─────────────────────────────────┬─────────────┘
                                                    ▼
                 ┌─────────────────────────────────────────────┐
                 │  Datastore: PostgreSQL (prod) / SQLite (local)│
                 └─────────────────────────────────────────────┘
```

Key cross-cutting pieces:

- **`app/core`** — config (env-driven, production-safety validation), structured logging,
  typed error envelope, security (Argon2id password hashing, JWT, TOTP).
- **`app/rules_engine`** — the `dsl` (parse/validate typed-JSON rules) and `evaluator`
  (deterministic scoring). No dynamic code execution.
- **`app/modules/audit`** — append-only, hash-chained audit events for tamper evidence.
- **Alembic migrations** — five ordered migrations build the schema in production.

## 3. Technology stack

| Layer      | Technology                                                        |
|------------|-------------------------------------------------------------------|
| Backend    | Python 3.13, FastAPI, SQLAlchemy 2.x, Pydantic v2, Alembic         |
| Jobs       | Dramatiq (worker wiring deferred; see ADR-0012)                   |
| Datastore  | PostgreSQL (production target), SQLite (local, dependency-free)    |
| Auth       | JWT (HS256) access + refresh tokens, Argon2id hashing, TOTP ready  |
| Frontend   | React 18, TypeScript (strict), Vite 6, React Query, React Router, React Hook Form, Zod |
| Tests      | pytest (backend), Vitest + Testing Library (frontend)             |
| Lint/Types | ruff + mypy (strict) backend; eslint + tsc (strict) frontend      |

## 4. Repository layout

```
backend/     FastAPI modular monolith
  app/
    core/          config, logging, errors, security
    db/            SQLAlchemy base, session, models registry
    api/           shared dependencies (auth actor, db session)
    rules_engine/  typed-JSON DSL + deterministic evaluator
    modules/       one folder per bounded context (router/service/repository/schemas/models)
    cli/           seed script (synthetic data)
  alembic/         five ordered migrations
  tests/           pytest suite (115 tests)
  run_local.py     zero-dependency SQLite runner
frontend/    React + TypeScript (Vite)
  src/
    api/           typed API client + auth + resources
    app/           router, layout, auth context
    components/    UI kit, toast, Orient HR Assistance
    pages/         one page per portal area
deploy/      docker-compose, reverse proxy, env template
seed/        synthetic-only demonstration data
docs/        this hub, ADRs, guides, threat model, checklists
.kiro/       steering rules + spec (requirements, design, tasks)
```

## 5. Running locally

Two ways to run: the **zero-dependency SQLite path** (fastest, no Docker/Postgres) or the
**full Docker stack**.

### 5a. Zero-dependency local run (recommended for evaluation)

Prerequisites: Python 3.13 and Node.js.

**Backend** (SQLite, auto-creates schema, seeds synthetic data):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe run_local.py
```

This serves the API at `http://localhost:8000` and interactive docs at
`http://localhost:8000/docs`. It writes a `local_dev.sqlite3` file in `backend/`.

**Frontend** (dev server, proxies `/api` → `:8000`):

```powershell
cd frontend
npm install
npm run dev     # or: node node_modules\vite\bin\vite.js --host --port 5173
```

Open `http://localhost:5173` and sign in with a seed account (section 6).

> Windows note: if `npm run dev` is blocked by PowerShell execution policy, run Vite
> directly: `node node_modules\vite\bin\vite.js --host --port 5173`.

### 5b. Full Docker stack

Prerequisites: Docker + Docker Compose.

```bash
cp deploy/.env.example deploy/.env     # fill in local-only secrets
docker compose -f deploy/docker-compose.yml up --build
```

| Service    | URL / port                 | Purpose                        |
|------------|----------------------------|--------------------------------|
| API        | http://localhost:8000      | FastAPI (`/health`, `/ready`)  |
| API docs   | http://localhost:8000/docs | OpenAPI (non-prod only)        |
| Frontend   | http://localhost:5173      | React dev server               |
| PostgreSQL | localhost:5432             | Primary datastore              |
| Redis      | localhost:6379             | Dramatiq broker / cache        |
| MinIO      | http://localhost:9001      | S3-compatible object storage   |
| MailHog    | http://localhost:8025      | Email sandbox                  |

See [deployment.md](deployment.md) for production deployment.

## 6. Seed accounts & roles

The seed creates **one synthetic staff user per role**. All share the same synthetic
password. These are for local evaluation only — never use them in a real environment.

- **Password (all accounts):** `SyntheticDevPassword123`
- **Email pattern:** `synthetic.<role>@example.com`

Three operational roles plus governance/public roles (full matrix:
[permission-matrix.md](permission-matrix.md)):

| Role (`<role>`)      | Email                                   | What they can do                                            |
|----------------------|-----------------------------------------|-------------------------------------------------------------|
| `recruiter`          | synthetic.recruiter@example.com         | Create projects/campaigns, author JD/rules, run screening, review applications, schedule interviews, manage waitlist — the **authoring** side of four-eyes |
| `recruiter_admin`    | synthetic.recruiter_admin@example.com   | Everything the recruiter does **plus** all approvals/sign-off: approve JDs, rules, thresholds, interviews & hiring decisions, correct candidate data, audited PII reveal. **No** system administration |
| `interview_panel`    | synthetic.interview_panel@example.com   | Confirm interview **attendance** and submit assessments for candidates they interview |
| `management_viewer`  | synthetic.management_viewer@example.com | Aggregated dashboards only (no candidate PII)               |
| `audit_viewer`       | synthetic.audit_viewer@example.com      | View the audit log                                          |
| `system_admin`       | synthetic.system_admin@example.com      | Manage users, system config, privacy requests. No automatic candidate-content access |

> The former `hr_head`, `hiring_manager`, and `recruitment_admin` accounts no longer exist;
> their duties are now held by `recruiter_admin`.

There is **no public staff signup**. Staff are created by a `system_admin` via
`POST /api/v1/users`. Candidates are never staff users — they apply through the public
endpoint. Separation-of-duties means author ≠ approver for rules and hiring decisions, so
use two different accounts for those flows (full permission matrix:
[permission-matrix.md](permission-matrix.md)).

## 7. The recruitment workflow end to end

The intended path through the platform:

1. **Set up** — a `recruiter` creates a **project**, then a **campaign** (approvals in the
   next step are done by a `recruiter_admin`, a different user, for four-eyes).
2. **Configure** — upload and **approve** a **job description** version; create and
   **approve** an **application form**; author and **approve** a **rule-set** (four-eyes)
   and set a **threshold**.
3. **Publish** — transition the campaign through its lifecycle to open it for applications.
4. **Apply** — candidates submit answers + resume via the **public apply** endpoint.
5. **Extract & verify** — resume fields are extracted; staff **review and correct** them.
6. **Screen** — run **deterministic screening**; each run is immutable and explainable and
   routes cases to review (never auto-rejects).
7. **Review** — reviewers act on the **review queue** (advance / hold / request info).
8. **Interview** — recruiters create **stages** and **slots**, approve **invitations**, and
   assign slots. The **Interview Panel** then confirms **attendance** from its own dashboard.
9. **Assess & decide** — the panel submits **assessments**; a `recruiter_admin` records the
   final **decision** (select/reject needs approval authority).
10. **Waitlist / talent pool** — waitlist candidates and **re-evaluate**; search the
    **talent pool** by skill.
11. **Govern** — handle **privacy** requests and retention; review **dashboards** and the
    **audit** log.

A copy-pasteable, call-by-call walkthrough of every endpoint in this order lives in
[api-reference.md](api-reference.md).

## 8. API reference

All endpoints are under `/api/v1`. Authenticated calls require
`Authorization: Bearer <access_token>`. The **authoritative, always-current** reference is
the interactive OpenAPI UI at `http://localhost:8000/docs` (available in non-production
only), where every endpoint can be run with "Try it out".

A grouped summary and a full worked example (every endpoint, in workflow order, with curl)
are in **[api-reference.md](api-reference.md)**.

Endpoint groups:

| Group            | Prefix                       | Purpose                                   |
|------------------|------------------------------|-------------------------------------------|
| Identity/auth    | `/api/v1/auth`, `/api/v1/users` | Login, refresh, me, user management     |
| Projects         | `/api/v1/projects`           | Create/list/get projects                  |
| Campaigns        | `/api/v1/campaigns`          | Create/list/get + lifecycle transition    |
| Job descriptions | `/api/v1/job-descriptions`   | Upload, edit draft, approve, revise        |
| Forms            | `/api/v1/forms`              | Create draft, approve                      |
| Rules            | `/api/v1/rules`              | Rule-set versions, approve, threshold change |
| Public apply     | `/api/v1/public`             | Unauthenticated candidate application      |
| Applications     | `/api/v1/applications`       | View, extracted fields, verify field       |
| Candidates       | `/api/v1/candidates`         | Get profile, talent-pool withdraw          |
| Screening        | `/api/v1/screening`          | Run screening, list runs                   |
| Reviews          | `/api/v1/reviews`            | List items, record actions                 |
| Interviews       | `/api/v1/interviews`         | Stages, slots, invitations, attendance     |
| Assessments      | `/api/v1/assessments`        | Submit assessment                          |
| Decisions        | `/api/v1/decisions`          | Record hiring decision                     |
| Waitlist         | `/api/v1/waitlist`           | Add, re-evaluate                           |
| Talent pool      | `/api/v1/talent-pool`        | Search by skill                            |
| Privacy          | `/api/v1/privacy`            | Requests, complete, retention policies     |
| Reports          | `/api/v1/reports`            | HR + management dashboards                 |
| Audit            | `/api/v1/audit`              | List hash-chained audit events             |

Health probes (unversioned): `GET /health`, `GET /ready`.

## 9. Frontend

The frontend is a single-page React app with a sidebar portal layout. Pages map to the
workflow areas: Dashboard, Projects, Campaigns, Campaign detail (tabs: overview / JD /
rules / form), Review queue, Talent pool, Management, Privacy, Admin, and a public Apply
page. An **Orient HR Assistance** helper (the 💬 button, bottom-right) is a rule-based,
deterministic assistant — no LLM — matching the platform's "runs without AI" principle.

Security note: JWTs are held **in memory only**, never in `localStorage`, per the security
steering. The Vite dev server proxies `/api/*` to the backend on port 8000.

Scripts (`frontend/package.json`): `npm run dev`, `npm run build`, `npm run typecheck`,
`npm run lint`, `npm run test`.

## 10. Configuration

Backend settings are environment-driven with the prefix `ORA_` (optionally from a `.env`
file in local dev). Defaults live in `backend/app/core/config.py`.

| Variable                        | Default                                   | Notes                                        |
|---------------------------------|-------------------------------------------|----------------------------------------------|
| `ORA_ENVIRONMENT`               | `development`                             | `development` / `test` / `staging` / `production` |
| `ORA_DATABASE_URL`              | `postgresql+psycopg://ora:ora@localhost:5432/ora` | SQLite accepted in dev only          |
| `ORA_JWT_SECRET`                | dev-only sentinel                         | Must be ≥32 chars & non-default in prod       |
| `ORA_JWT_ALGORITHM`             | `HS256`                                   |                                              |
| `ORA_ACCESS_TOKEN_TTL_SECONDS`  | `900` (15 min)                            | Short-lived access token                      |
| `ORA_REFRESH_TOKEN_TTL_SECONDS` | `1209600` (14 days)                       |                                              |
| `ORA_MAX_FAILED_LOGINS`         | `5`                                       | Account lockout threshold                     |
| `ORA_LOCKOUT_SECONDS`           | `900` (15 min)                            |                                              |
| `ORA_CORS_ALLOWED_ORIGINS`      | `http://localhost:5173`                   | Comma-separated; no localhost in prod         |
| `ORA_LLM_ADAPTER_ENABLED`       | `false`                                   | AI is advisory-only and off by default        |

**Production safety:** on startup in `staging`/`production`, the app refuses to boot if the
JWT secret is weak/default, if CORS allows localhost, or if `ORA_DATABASE_URL` is SQLite.

## 11. Security & privacy model

- **Authentication:** JWT access + refresh tokens; Argon2id password hashing; account
  lockout after repeated failures; TOTP support available.
- **Authorisation:** fine-grained permissions bundled into roles, plus **object-level**
  campaign/application scoping on top. See [permission-matrix.md](permission-matrix.md).
- **Separation of duties / four-eyes:** rule-set approval and select/reject decisions
  require an approver different from the author.
- **Explainability:** screening is deterministic and reproducible; every score is
  evidence-backed; the system never auto-rejects and never requires an LLM.
- **Audit:** append-only, hash-chained audit events provide tamper evidence.
- **Privacy:** data subject access/erasure requests, retention policies, and
  candidate-controlled talent-pool withdrawal. See
  [candidate-privacy-flow.md](candidate-privacy-flow.md) and
  [privacy-checklist.md](privacy-checklist.md).
- **Secrets:** never commit real credentials, candidate data, resumes, tokens, or keys.
  All seed/test data is synthetic and clearly marked.

Deeper material: [threat-model.md](threat-model.md),
[security-checklist.md](security-checklist.md).

## 12. Testing & quality gates

**Backend** (from `backend/`, venv active):

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests     # lint
.\.venv\Scripts\python.exe -m mypy app                 # strict type-check
.\.venv\Scripts\python.exe -m pytest tests -q          # 115 tests
```

**Frontend** (from `frontend/`):

```powershell
npm run typecheck     # tsc --noEmit (strict, exactOptionalPropertyTypes)
npm run lint          # eslint
npm run test          # vitest run
```

Current status: backend 115 tests passing with ruff + mypy clean; frontend typechecks clean
with tests passing.

## 13. Deployment

Production uses PostgreSQL with Alembic migrations (`alembic upgrade head`) — never the
SQLite dev runner, and never the synthetic seed. See [deployment.md](deployment.md) and
[backup-restore.md](backup-restore.md). The product is not claimed to be automatically
legally compliant and is not claimed to be risk-free; review the threat model and
checklists before any real-world use.

## 14. Further reading

| Document                                             | What it covers                              |
|------------------------------------------------------|---------------------------------------------|
| [api-reference.md](api-reference.md)                 | Full endpoint reference + worked example    |
| [admin-guide.md](admin-guide.md)                     | System-admin operations                     |
| [hr-guide.md](hr-guide.md)                           | Day-to-day HR/recruiter usage               |
| [state-machines.md](state-machines.md)               | Campaign/application lifecycle transitions  |
| [permission-matrix.md](permission-matrix.md)         | Role → permission mapping                   |
| [candidate-privacy-flow.md](candidate-privacy-flow.md)| Candidate data & consent flow              |
| [threat-model.md](threat-model.md)                   | STRIDE-style threat analysis                |
| [security-checklist.md](security-checklist.md)       | Pre-release security checks                 |
| [privacy-checklist.md](privacy-checklist.md)         | Privacy/retention checks                    |
| [deployment.md](deployment.md)                       | Production deployment                       |
| [backup-restore.md](backup-restore.md)               | Backup & restore procedures                 |
| [open-decisions.md](open-decisions.md)               | Known open questions / deferred decisions   |
| [adr/](adr/)                                         | Architecture Decision Records               |

---

_All example data, accounts, and credentials in this documentation are synthetic and for
local evaluation only._

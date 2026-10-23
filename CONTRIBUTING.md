# Contributing — Orient Recruitment Accelerator

This guide covers local setup, the development workflow, project conventions, and the
quality gates every change must pass. For product and architecture context, start with
[docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md).

> All seed/test data is synthetic and clearly marked. Never commit real credentials,
> candidate data, resumes, secrets, tokens, or production configuration.

## 1. Prerequisites

- Python 3.12+ (3.13 works locally; CI targets 3.12)
- Node.js 20+
- Optional: Docker + Docker Compose (for the full stack with PostgreSQL/Redis/MinIO/MailHog)

## 2. First-time setup

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

### Frontend

```powershell
cd frontend
npm install
```

## 3. Running locally

Fastest path (no Docker) — SQLite + auto-seed:

```powershell
# Terminal 1 — backend at http://localhost:8000 (docs at /docs)
cd backend
.\.venv\Scripts\python.exe run_local.py

# Terminal 2 — frontend at http://localhost:5173 (proxies /api -> :8000)
cd frontend
npm run dev
```

Sign in with a synthetic account, e.g. `synthetic.hr_head@example.com` /
`SyntheticDevPassword123` (full list in [docs/PROJECT_DOCUMENTATION.md](docs/PROJECT_DOCUMENTATION.md)).

Full Docker stack: `docker compose -f deploy/docker-compose.yml up --build` (see
[docs/deployment.md](docs/deployment.md)).

## 4. Quality gates (run before every PR)

These mirror the CI pipeline (`.github/workflows/ci.yml`). A change must pass all of them.

**Backend** (from `backend/`, venv active):

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests    # format + lint
.\.venv\Scripts\python.exe -m mypy app                # strict type check
.\.venv\Scripts\python.exe -m pytest tests -q         # unit + integration
```

**Frontend** (from `frontend/`):

```powershell
npm run typecheck    # tsc --noEmit (strict, exactOptionalPropertyTypes)
npm run lint         # eslint
npm run test         # vitest run
```

CI additionally runs Alembic migration validation (upgrade → downgrade → upgrade),
`pip-audit` (report-only for now), gitleaks secret scanning, and the frontend build.

## 5. Project conventions

### Architecture & layering (strict)

```
router (thin: auth, validation, serialization — NO business logic)
  -> service   (orchestration, transaction boundaries)
    -> policy  (invariants, separation-of-duties, state guards)
      -> repository (data access, org/campaign scoped)
        -> database
```

- Routers contain **no** business logic.
- ORM models are **never** serialized directly — map to Pydantic schemas.
- Modules talk through service interfaces, not each other's repositories/models.
- Mandatory choke points: screening → Screening Service; campaign status → Transition
  Service; sensitive actions → audit event.

### Backend module layout

Every module under `backend/app/modules/<name>/` follows:

```
router.py   service.py   policy.py   repository.py   models.py   schemas.py
```

### Coding standards

- **Python:** type hints throughout, mypy clean; ruff for format + lint; Pydantic v2 at all
  request/response boundaries; SQLAlchemy 2.x typed models; no raw SQL from user input.
- **TypeScript/React:** strict mode, no implicit `any`; Zod validates all external data;
  React Hook Form for forms; TanStack Query for server state; **no sensitive data in
  localStorage/sessionStorage**; components accessible by default (labels, roles, focus).
- Clear domain names (`ScreeningRun`, `TransitionService`, `JDVersion`) — avoid generic
  `manager`/`handler`/`processor`.
- Handle errors explicitly; never log sensitive inputs; add a short rationale comment on
  security-sensitive code.

### Absolute prohibitions

No `eval`/`exec`; no dynamic SQL from user input; no `pickle` of untrusted data; no OS
shell calls using user input; no hard-coded secrets. Rules are **data** (typed JSON DSL),
never code.

### Database

UUID PKs; UTC `created_at`/`updated_at`; `created_by`/`updated_by` where appropriate;
optimistic concurrency (`version`) where edits race; org key on every scoped table.
Approved versioned entities (JDVersion, RuleSetVersion, ThresholdVersion, ScreeningRun) are
immutable — changes create new versions. All schema changes go through Alembic migrations.

### API standards

All routes under `/api/v1/`. Pydantic request/response models. Consistent error envelope
`{ "error": { "code", "message", "correlation_id", "details"? } }`. Server-side permission
**and** object-level authorisation on every endpoint, independent of the UI. Each endpoint
documents its required permission(s) via OpenAPI.

## 6. Testing expectations

- Add tests with new features/bug fixes (test-first where practical).
- Prove rules-engine regressions: identical inputs + rule version → identical results; rule
  changes create new versions and old results stay reproducible; mandatory criteria and
  missing/low-confidence routing behave correctly.
- Frontend: component, form-validation, permission-state, accessibility (axe), and
  critical-workflow tests.
- See `.kiro/steering/testing.md` for the full strategy.

## 7. Git workflow

- Branch off `main`; never push directly to `main`.
- Use clear, scoped commits. Stage specific files rather than `git add -A`.
- Open a PR; CI must be green. Keep PR titles under ~70 characters; describe the change,
  what was tested, and anything deferred.
- Never commit secrets or real candidate data. Flag any `.env`/credential-looking file.
- Don't skip hooks or force-push shared branches without explicit agreement.

## 8. Adding a new backend module (checklist)

1. Create `backend/app/modules/<name>/` with the six standard files.
2. Define ORM models (org-scoped) and an Alembic migration.
3. Keep business logic in `service.py`; invariants/SoD in `policy.py`.
4. Expose a thin `router.py` under `/api/v1/<group>` with permission + campaign checks.
5. Register the router in `backend/app/main.py`.
6. Add tests (unit + API integration). Run the quality gates in section 4.

## 9. Where things live

- Steering (binding norms): `.kiro/steering/*.md`
- Spec (requirements/design/tasks): `.kiro/specs/recruitment-platform/`
- Docs (reference/guides/ADRs): `docs/`
- CI: `.github/workflows/ci.yml`

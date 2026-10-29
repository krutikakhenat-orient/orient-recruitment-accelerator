# Orient Recruitment Accelerator

A production-quality, secure, and **explainable** recruitment campaign management and
candidate screening platform.

> Status: **All 7 phases implemented.** Backend: full pytest suite passing, ruff + mypy
> (strict) clean. Frontend: strict TypeScript, typecheck + tests passing. See
> `.kiro/specs/recruitment-platform/tasks.md` for the implementation plan.
>
> Recent additions: an **HR campaign report** with a clean two-sheet **Excel export**
> (Candidates + Summary) and a matching **in-app Preview Excel** view — both built from one
> shared model so preview and download are identical (searchable/scrollable table, overall
> score vs JD-skills-match, derived strengths & missing/unverified requirements, masked PII
> unless `candidate.view_pii`); a per-candidate **Candidate summary** dashboard; a secure
> per-candidate **Download résumé** action/link (original file only, *Resume unavailable*
> when none); **role-based interviewer assignment** with strict interview-panel isolation;
> and a **glassmorphic UI** refresh (frosted cards, muted blue/lavender accents, subtle
> motion honouring `prefers-reduced-motion`). See
> [docs/permission-matrix.md](docs/permission-matrix.md) and
> [docs/api-reference.md](docs/api-reference.md).

## Core principles

AI may extract, normalise, summarise and recommend — it **never** makes the final hiring
decision. Mandatory eligibility and weighted scoring use deterministic, version-controlled
rules; every score is reproducible and evidence-backed. The system runs fully without any
LLM service. See `.kiro/steering/` for the normative rules.

## 📚 Documentation

**Full documentation lives in [`docs/`](docs/README.md).** Start there. Highlights:

- [docs/README.md](docs/README.md) — documentation hub (architecture, workflow, config, security)
- [docs/api-reference.md](docs/api-reference.md) — every endpoint + a worked curl example
- [docs/hr-guide.md](docs/hr-guide.md) / [docs/admin-guide.md](docs/admin-guide.md) — usage guides
- [docs/state-machines.md](docs/state-machines.md) — lifecycle transitions
- [docs/permission-matrix.md](docs/permission-matrix.md) — role → permission mapping
- [docs/threat-model.md](docs/threat-model.md) — security analysis

## Repository layout

```
backend/     FastAPI modular monolith (Python 3.13, SQLAlchemy 2.x, Alembic) — see backend/README.md
frontend/    React + TypeScript (Vite) — see frontend/README.md
deploy/      docker-compose, reverse proxy, env template
seed/        synthetic-only demonstration data
docs/        documentation hub, ADRs, threat model, guides
.kiro/       steering + spec (requirements, design, tasks)
```

Contributing and security:

- [CONTRIBUTING.md](CONTRIBUTING.md) — setup, workflow, conventions, quality gates
- [SECURITY.md](SECURITY.md) — vulnerability reporting and security posture

## Quick start — zero-dependency local run

No Docker/PostgreSQL required. The backend runs against a local SQLite file and seeds
synthetic data automatically. Prerequisites: Python 3.13 and Node.js.

**Backend** (serves API at http://localhost:8000, docs at /docs):

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe run_local.py
```

**Frontend** (serves app at http://localhost:5173, proxies /api → :8000):

```powershell
cd frontend
npm install
npm run dev
```

Then open http://localhost:5173 and sign in with a seed account:

- Email: `synthetic.recruiter_admin@example.com` (or any `synthetic.<role>@example.com`)
- Password: `SyntheticDevPassword123`

> Note: the former `hr_head` and `hiring_manager` roles were merged into **Recruiter
> Admin**; use `synthetic.recruiter_admin@example.com` for approvals and decisions.

Full role list and the complete setup → screening → decision walkthrough are in
[docs/README.md](docs/README.md).

## Quick start — full Docker stack

Prerequisites: Docker + Docker Compose.

```bash
cp deploy/.env.example deploy/.env     # fill in local-only secrets
docker compose -f deploy/docker-compose.yml up --build
```

| Service    | URL / port                | Purpose                       |
|------------|---------------------------|-------------------------------|
| API        | http://localhost:8000     | FastAPI (`/health`, `/ready`) |
| API docs   | http://localhost:8000/docs| OpenAPI (non-prod)            |
| Frontend   | http://localhost:5173     | React dev server              |
| PostgreSQL | localhost:5432            | Primary datastore             |
| Redis      | localhost:6379            | Dramatiq broker / cache       |
| MinIO      | http://localhost:9001     | S3-compatible object storage  |
| MailHog    | http://localhost:8025     | Email sandbox                 |

## Quality gates

```powershell
# Backend (from backend/, venv active)
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest tests -q

# Frontend (from frontend/)
npm run typecheck
npm run lint
npm run test
```

## Security & privacy

Never commit real credentials, production candidate data, resumes, secrets, tokens, or
private keys. All seed/test data is synthetic and clearly marked. The product is not
claimed to be automatically legally compliant and is not claimed to be risk-free; review
[docs/threat-model.md](docs/threat-model.md) and the checklists in `docs/` before any
real-world use.

# Backend — Orient Recruitment Accelerator

FastAPI modular monolith. Python 3.12+, SQLAlchemy 2.x, Pydantic v2, Alembic.

For product/architecture context see [../docs/PROJECT_DOCUMENTATION.md](../docs/PROJECT_DOCUMENTATION.md);
for workflow and conventions see [../CONTRIBUTING.md](../CONTRIBUTING.md).

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## Run (local, zero-dependency)

```powershell
.\.venv\Scripts\python.exe run_local.py
```

Serves the API at http://localhost:8000 against a local SQLite file, creating the schema
and seeding synthetic data. Interactive docs at http://localhost:8000/docs. Health probes:
`/health`, `/ready`.

Production uses PostgreSQL with Alembic migrations (`alembic upgrade head`), never the
SQLite runner or the synthetic seed.

## Quality gates

```powershell
.\.venv\Scripts\python.exe -m ruff check app tests
.\.venv\Scripts\python.exe -m mypy app
.\.venv\Scripts\python.exe -m pytest tests -q
```

## Layout

```
app/
  core/          config, logging, errors, security, correlation
  db/            SQLAlchemy base, session, model registry
  api/           shared dependencies (auth actor, db session, settings)
  rules_engine/  typed-JSON DSL + deterministic evaluator (no eval/exec)
  modules/<name>/  router.py service.py policy.py repository.py models.py schemas.py
  cli/           synthetic seed script
  main.py        app factory, middleware, router registration
alembic/         ordered migrations
tests/           pytest suite
run_local.py     zero-dependency SQLite runner
```

## Configuration

Environment variables use the `ORA_` prefix (see `app/core/config.py`). Defaults are safe
for local dev; production-like environments fail fast on insecure defaults. Full table in
[../docs/PROJECT_DOCUMENTATION.md](../docs/PROJECT_DOCUMENTATION.md#12-configuration).

> Synthetic data only. Never commit real credentials or candidate data.

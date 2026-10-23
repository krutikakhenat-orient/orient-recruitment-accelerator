# Deployment

## Local development (clean environment → running app)

Prerequisites: Docker + Docker Compose.

```bash
cp deploy/.env.example deploy/.env         # fill local-only values
docker compose -f deploy/docker-compose.yml up --build
```

This starts PostgreSQL, Redis, MinIO, MailHog, the API (which runs `alembic upgrade head`
on start), and the frontend dev server. Then seed synthetic data:

```bash
docker compose -f deploy/docker-compose.yml exec api python -m app.cli.seed
```

Services: API `:8000` (`/health`, `/ready`, `/docs`), frontend `:5173`, Postgres `:5432`,
Redis `:6379`, MinIO console `:9001`, MailHog UI `:8025`.

## Backend without Docker

```bash
cd backend
python -m venv .venv && .\.venv\Scripts\Activate.ps1   # Windows PowerShell
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload
pytest
```

## Production gates (must all pass before deploy)
Per `.kiro/steering/devsecops.md`: successful CI pipeline, reviewed migration, security
checks passed, environment validation, backup confirmation, rollback plan, and a human
release approval. The app refuses to start in a production-like environment with insecure
default secrets (`core/config.validate_production_safety`).

## Production configuration notes
- Set a strong `ORA_JWT_SECRET` (≥32 chars) and non-localhost `ORA_CORS_ALLOWED_ORIGINS`.
- Terminate TLS at the reverse proxy; the app sets HSTS when `ORA_ENVIRONMENT` is
  staging/production.
- Replace the development malware scanner with a real ClamAV-compatible scanner.
- Point the object-store adapter at S3/MinIO with server-side encryption enabled.
- Run migrations as a reviewed, separate step before rolling out new app instances.

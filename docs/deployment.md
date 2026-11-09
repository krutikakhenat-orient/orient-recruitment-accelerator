# Deployment

## Deployment methods

| Method | Location | Status |
|---|---|---|
| Terraform (Orient_Internal_AI account) | `Orient_Internal_AI_Deployment/` | Current AWS path |
| AWS CDK (Python) | `deploy/aws/` | Supported |
| Bedrock AgentCore (interview agent) | `interview-agent/InterviewAgent/agentcore/` | Supported |
| AWS Amplify (Gen 2 auth / hosting) | `amplify.yml`, `amplify-backend/` | Supported |
| Docker Compose | `archive/docker-compose/` | **Deprecated, archived. Do not use.** |

## Local development (clean environment → running app)

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe run_local.py     # SQLite + auto-seed, API at :8000
```

```powershell
cd frontend
npm install
npm run dev                                 # app at :5173, proxies /api to :8000
```

## Backend manual setup

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

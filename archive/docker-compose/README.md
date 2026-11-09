# ARCHIVED: Docker Compose deployment (deprecated)

**Status: deprecated and unsupported. Do not use, extend, or reference this for new work.**

This folder holds the former local "full stack" Docker Compose deployment (API, frontend
dev server, PostgreSQL, Redis, MailHog). It is kept only for history and is not part of
the current codebase. Nothing in CI, the AWS CDK stack, the Terraform deployment, Amplify,
or the AgentCore deployment depends on it.

## Archived files

| Archived path | Original path |
|---|---|
| `deploy/docker-compose.yml` | `deploy/docker-compose.yml` |
| `deploy/.env.example` | `deploy/.env.example` |
| `backend/Dockerfile` | `backend/Dockerfile` |
| `backend/.dockerignore` | `backend/.dockerignore` |
| `frontend/Dockerfile` | `frontend/Dockerfile` |

## Why it was archived

- It was not used for any real deployment.
- Its MinIO service was already removed (the backend object store defaults to an
  in-memory implementation), so it did not match the running architecture.
- Keeping it next to the supported methods confused contributors and AI agents about
  which deployment path is current.

## Current ways to run and deploy

- Local development: `backend/run_local.py` (SQLite + auto-seed) and `npm run dev` in
  `frontend/`. See the root `README.md` and `CONTRIBUTING.md`.
- AWS: `Orient_Internal_AI_Deployment/` (Terraform) is the current path for the
  Orient_Internal_AI account. `deploy/aws/` (CDK) is the other AWS method.
- Interview agent: `interview-agent/InterviewAgent/agentcore/`.

## Restoring

History is preserved with `git mv`. To restore, move the files back to the original paths
listed above (`git log --follow <file>` shows the earlier history). Review and update
dependencies and images first, since this setup has not been maintained.

---
inclusion: always
---

# DevSecOps

## CI pipeline (runs on every change)
Code formatting check, linting, type checking, unit tests, integration tests, frontend
tests, accessibility checks, dependency scanning, secret scanning, static security
analysis (SAST), container image scanning, migration validation, build verification.

## Production deployment gates (all required)
Successful pipeline, reviewed migration, security checks passed, environment validation,
backup confirmation, rollback plan, human release approval.

## Local development environment provides
`backend/run_local.py` (SQLite, auto-seeded with synthetic data), developer setup
instructions, migration/test/lint/build commands, health checks. The Docker Compose
environment (MinIO, MailHog, PostgreSQL, Redis) is deprecated and archived in
`archive/docker-compose/`.

## Never commit
Real credentials, production candidate data, resumes, secrets, access tokens, private keys,
production configuration.

## Observability
Structured logs with correlation IDs and no candidate PII; metrics; tracing readiness;
health and readiness endpoints.

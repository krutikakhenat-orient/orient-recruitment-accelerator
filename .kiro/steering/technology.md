---
inclusion: always
---

# Technology stack

## Backend
- Python 3.12 (current stable supported release)
- FastAPI (HTTP), Pydantic v2 (schemas/validation)
- SQLAlchemy 2.x (ORM), Alembic (migrations)
- PostgreSQL (primary datastore)
- Dramatiq (background jobs) + Redis (broker/cache only where justified)

## Frontend
- React + TypeScript (strict mode), Vite
- React Router, TanStack Query, React Hook Form, Zod
- Accessible component system (WCAG-oriented)

## File storage
- S3-compatible object storage behind a storage abstraction
- MinIO for local development

## Document processing (baseline, no external LLM)
- PDF text extraction (PyMuPDF / pdfminer.six)
- DOCX extraction (python-docx)
- OCR fallback for image-based documents (Tesseract via pytesseract)
- Pluggable parser adapter; manual verification workflow
- Malware scanning behind an adapter interface (ClamAV-compatible for dev;
  a no-op scanner is explicitly flagged non-production)

## Authentication
- Local dev identity provider: username/password with Argon2id hashing + TOTP MFA scaffold
- Architecture ready for OIDC/SAML enterprise integration behind an auth-provider interface

## Notifications
- Provider-neutral email adapter; MailHog dev sandbox
- Template versioning; delivery and failure tracking

## Deployment
- Docker + Docker Compose (local), reverse proxy, environment-based config, Linux target

## Testing
- Backend: pytest. Frontend: Vitest + Testing Library. API integration, e2e (Playwright),
  security tests, accessibility tests (axe).

## Observability
- Structured logs (no candidate PII), metrics, tracing readiness, health/readiness endpoints.

## Version & dependency policy
- Pin dependencies. Run dependency vulnerability scanning, secret scanning, SAST, and
  container image scanning in CI.

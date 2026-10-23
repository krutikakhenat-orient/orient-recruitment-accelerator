# Security Checklist

Status key: ✅ implemented in MVP · ◻ readiness/interface present, enable for production.

## Authentication & session
- ✅ Argon2id password hashing
- ✅ Short-lived access tokens; distinct refresh tokens (type claim)
- ✅ Account lockout + login-anomaly audit
- ✅ Uniform auth errors (no user enumeration)
- ◻ MFA enforcement (TOTP scaffold present)
- ◻ OIDC/SAML enterprise SSO (interface present)
- ◻ Secure/HttpOnly/SameSite cookies + CSRF for cookie flows (headers middleware present)

## Authorization
- ✅ Fine-grained permissions bundled into roles
- ✅ Object-level authorisation (campaign/application assignment)
- ✅ Separation of duties (rule creator ≠ sole approver)
- ✅ Four-eyes threshold changes

## Input / output
- ✅ Pydantic validation on all request bodies
- ✅ Parameterised DB access (no dynamic SQL)
- ✅ Consistent sanitised error envelope (no internal leakage on 500)
- ✅ Security headers (CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy)
- ◻ HSTS in production-like environments (set when is_production_like)
- ◻ Restricted CORS (configured; must set non-localhost origins in prod)

## Uploads & documents
- ✅ Extension + declared-MIME + magic-byte signature validation
- ✅ Upload size cap; zip-bomb-safe DOCX extraction
- ✅ Quarantine → malware-scan adapter → clean/infected
- ✅ uuid-based safe storage keys (path-traversal defence)
- ◻ Production malware scanner (ClamAV) — dev scanner is NOT production-grade
- ◻ Signed short-lived download links (object-store abstraction ready)

## Data protection
- ✅ Org-scoped repositories (tenant isolation)
- ✅ PII-safe structured logging with redaction
- ✅ Append-only audit with prev-hash chain
- ◻ Field-level encryption for sensitive PII (open decision)
- ◻ Storage/DB encryption at rest (deployment responsibility)

## Supply chain / CI
- ✅ Pinned dependencies
- ✅ CI: ruff, mypy, pytest, migration up/down, pip-audit, gitleaks
- ◻ SAST (Bandit/CodeQL) and container image scanning (Trivy) — enable as images stabilise

## AI safety
- ✅ Documents treated as untrusted data; never executed
- ✅ Prompt-injection / keyword-stuffing / hidden-text flagged, not acted on
- ✅ LLM adapter disabled by default; deterministic pipeline is authoritative

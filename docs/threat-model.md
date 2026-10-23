# Threat Model — Orient Recruitment Accelerator

Scope: the MVP backend (FastAPI modular monolith), its PostgreSQL store, object storage,
and the public candidate application endpoint. Method: STRIDE + OWASP Top 10 + domain
threats. Each threat lists the mitigation and where it lives in code.

## Trust boundaries
1. Public internet → public application endpoint (`/api/v1/public/...`). Untrusted.
2. Authenticated staff → `/api/v1/...`. Authenticated + object-level authorised.
3. Uploaded documents (JD, resume) → untrusted data, never executed.
4. Object storage and DB → internal; files reachable only via the app.
5. Optional LLM adapter → external, disabled by default, output schema-validated.

## STRIDE / OWASP coverage

| Threat | Mitigation | Where |
|---|---|---|
| Spoofing / broken auth | Argon2id, short-lived access tokens, protected refresh, lockout, anomaly audit | core/security, identity/service |
| Tampering (data/audit) | Optimistic concurrency; append-only audit with prev-hash chain | db/base, audit/service |
| Repudiation | Every sensitive action emits an audit event with actor + reason | audit/service, all services |
| Information disclosure / IDOR | Object-level authz on every endpoint; org-scoped repositories; no PII in logs | identity/policy, core/logging |
| Denial of service | Upload size cap, zip-bomb-safe DOCX read, rate-limit strategy (per endpoint class) | documents/validation, extraction |
| Elevation of privilege | Fine-grained permissions + object scope; SoD; four-eyes thresholds | identity/policy, rules/service |
| Injection (SQLi) | SQLAlchemy parameterised access only; no dynamic SQL from input | repositories |
| XSS | API returns JSON; frontend escapes; CSP header | main.py, frontend |
| CSRF | SameSite + Secure cookies, CSRF for cookie flows | security.md |
| SSRF | Egress allow-list for any outbound adapter; no fetch of user URLs | security.md (hardening) |
| Mass assignment | Pydantic request models with explicit fields; no blind ORM binding | schemas |
| Path traversal | uuid-based storage keys; original filename never used as a path | documents/validation |
| Malicious upload | ext+MIME+signature validation, quarantine, malware-scan adapter | documents/service |
| Zip bomb | Decompression size ceiling on DOCX part | extraction/text_extractors |
| CSV/formula injection | Export neutralisation (hardening task) | reporting (export, planned) |
| Credential stuffing / enumeration | Lockout + uniform generic auth errors | identity/service |
| Bot submissions | Public-endpoint rate-limit + CAPTCHA readiness | applications/router |
| Prompt injection in resumes | Treated as data; flagged, never executed; LLM output advisory-only | extraction/resume_extractor |
| Hidden text / keyword stuffing | Heuristic flags reduce confidence → human review | extraction/resume_extractor |
| Excessive data export | candidate.export permission + audit + volume limits (planned) | identity, audit |

## Residual risks / non-claims
- The development malware scanner is NOT production-grade; a real ClamAV-compatible
  scanner must be wired for production.
- The product is not claimed to be automatically legally compliant, nor risk-free.
- Field-level encryption and WORM audit storage are readiness items, not yet implemented.

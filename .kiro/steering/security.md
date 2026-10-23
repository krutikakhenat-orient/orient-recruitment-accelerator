---
inclusion: always
---

# Security (secure by default)

## AuthN / AuthZ
- Argon2id password hashing for local credentials; OIDC/SAML-ready auth interface.
- MFA readiness (TOTP scaffold). Short-lived access tokens; protected refresh tokens.
- Secure, HttpOnly, SameSite cookies; CSRF protection for cookie-based flows.
- Account lockout + login anomaly logging; rate limiting on auth and public endpoints.
- **Object-level authorisation** everywhere: a permission is always checked against the
  specific campaign/application the actor is assigned to. Server-side checks are
  authoritative regardless of hidden UI.

## Separation of duties
- Creator of an exclusion rule cannot be its sole approver.
- Threshold changes require a different authorised approver when four-eyes is configured.
- Interview panel members cannot alter screening rules.
- Candidates cannot view internal scores, reviewer comments, or other candidate records.
- Auditors are read-only. System administrators get no automatic candidate-content access.

## Web / API hardening
- Input validation; output encoding; parameterised DB access only.
- Restricted CORS; CSP; HSTS; security headers; error-message sanitisation.
- Idempotency keys for sensitive creation endpoints; optimistic concurrency.
- No PII in URL paths where avoidable; PII-safe logging.

## File upload safety
- Validate extension + MIME + file signature; enforce size limits.
- Quarantine before processing; malware-scan adapter; file hash + duplicate detection.
- Safe generated filenames; no execution/rendering of untrusted content.
- No direct public object-storage access; signed short-lived download links only.
- Decompression limits (zip-bomb protection); strip active content/unsafe metadata.
- CSV/formula-injection neutralisation on all exports.

## Threats to defend (OWASP + domain)
SQLi, XSS, CSRF, SSRF, broken access control, IDOR, mass assignment, path traversal,
malicious upload, zip bombs, CSV formula injection, credential stuffing, bot submissions,
enumeration, prompt injection in resumes, hidden text / keyword stuffing in resumes,
malicious document metadata, excessive data export.

## Data protection
- Encryption in transit; storage/DB encryption readiness; sensitive-field encryption strategy.
- Secrets outside source control; environment validation at startup.
- Dependency pinning + vulnerability scanning; container scanning; backup encryption.

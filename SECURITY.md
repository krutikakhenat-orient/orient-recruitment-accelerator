# Security Policy

Security and candidate-data protection are first-order concerns for the Orient Recruitment
Accelerator. This document explains how to report a vulnerability and summarises the
platform's security posture. For the full analysis see
[docs/threat-model.md](docs/threat-model.md) and
[docs/security-checklist.md](docs/security-checklist.md).

## Reporting a vulnerability

- **Do not** open a public issue for security problems.
- Report privately to the project's security contact / maintainers (replace with your
  organisation's security channel before publishing this repository).
- Include: affected component, reproduction steps, impact, and any logs **with sensitive
  values redacted**. Do not include real candidate data.
- You will receive an acknowledgement; please allow reasonable time for a fix before any
  public disclosure.

Please avoid testing that could expose or destroy real data, degrade service for others, or
access accounts/records that are not yours.

## Supported scope

This repository is an MVP build. Security fixes target the current `main` branch. The
product is **not** claimed to be automatically legally compliant and is **not** claimed to
be risk-free.

## Security posture (summary)

- **Authentication:** Argon2id password hashing; short-lived JWT access tokens + refresh
  tokens; account lockout after repeated failures; TOTP MFA scaffold; OIDC/SAML-ready auth
  interface.
- **Authorisation:** fine-grained permissions bundled into roles, plus **object-level**
  authorisation (actor must be assigned to the specific campaign). Checks are server-side
  and authoritative regardless of the UI.
- **Separation of duties / four-eyes:** the creator of a rule-set or threshold cannot be
  its approver; select/reject decisions require approval authority.
- **Web/API hardening:** input validation, output encoding, parameterised DB access,
  restricted CORS, CSP/security headers, sanitised error messages, correlation IDs.
- **File-upload safety:** extension + MIME + signature validation, size limits, quarantine
  before processing, malware-scan adapter, file hash + duplicate detection, no execution of
  untrusted content, CSV/formula-injection neutralisation on exports.
- **Documents as untrusted data:** resumes and JDs never override system instructions or
  trigger tools/network/DB/code; defences against prompt injection, hidden text, and
  keyword stuffing.
- **Responsible AI:** screening is deterministic and reproducible; AI never makes the final
  decision; no auto-reject; protected/medical attributes never used as criteria.
- **Audit:** append-only, per-organisation hash-chained events for tamper evidence.
- **Secrets & config:** secrets come from the environment; startup validation blocks
  insecure defaults (weak JWT secret, localhost CORS, SQLite) in production-like
  environments; the dev-only API router is not registered in production.
- **Supply chain (CI):** dependency vulnerability scanning (`pip-audit`) and secret
  scanning (gitleaks) run in CI; container scanning and SAST are planned (see
  [docs/open-decisions.md](docs/open-decisions.md)).

## Known limitations (not yet production-hardened)

Tracked in [docs/open-decisions.md](docs/open-decisions.md). Notably: field-level PII
encryption is not yet implemented; the local malware scanner is a dev stand-in (not
production-grade); signed short-lived download links are not yet wired; and container
scanning / SAST are not yet in CI. These must be addressed before any real-world use.

## Handling data

All seed and test data is synthetic and clearly marked. Never commit real credentials,
production candidate data, resumes, secrets, access tokens, private keys, or production
configuration. Logs must not contain candidate PII.

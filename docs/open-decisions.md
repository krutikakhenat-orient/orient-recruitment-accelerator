# Open Decisions & Limitations Register

Items deliberately deferred or flagged during the MVP build. Each has a safe default now
and a decision owner later. None of these are claimed to be resolved.

| # | Topic | Current state (safe default) | To decide |
|---|---|---|---|
| 1 | Field-level encryption for sensitive PII | Not implemented; org-scoped access + PII-safe logging in place | Mechanism: app-layer envelope vs pgcrypto vs KMS |
| 2 | Audit tamper-evidence upgrade | Per-event prev-hash chain (verifiable) | Whether to add WORM storage / periodic Merkle anchoring |
| 3 | Re-evaluation approval granularity | Per-run reason + audit; new comms require separate approval | Per-run vs per-campaign-batch approval |
| 4 | First enterprise SSO protocol | Local Argon2id + TOTP scaffold; auth-provider interface ready | OIDC vs SAML first |
| 5 | Production OCR engine | Tesseract fallback assumed; reports unavailable if absent | Licensing/accuracy posture for production |
| 6 | Production malware scanner | Dev scanner (EICAR-aware) is NOT production-grade | Wire ClamAV-compatible scanner |
| 7 | Background worker wiring | Services run in-transaction; Dramatiq chosen (ADR-0012) | Move document processing / retention jobs to async workers |
| 8 | Signed download links | Object-store abstraction ready; no public access | Implement signed short-lived URLs for candidate/staff downloads |
| 9 | Multi-tenancy | Single-org MVP; org key on every table | Whether/when to add full SaaS isolation |
| 10 | Candidate self-service auth | Privacy actions exposed to staff (privacy_request.manage) | Candidate login for self-service corrections/withdrawal |
| 11 | Frontend portals | API complete + accessible login/home skeleton; portals pending | Build candidate/recruiter/manager/panel/admin/privacy UIs |
| 12 | CI SAST + container scan | ruff/mypy/pytest/migration/pip-audit/gitleaks in CI | Add Bandit/CodeQL + Trivy once images stabilise |

## Non-claims
The product is not claimed to be automatically legally compliant, nor risk-free. Synthetic
data is clearly marked and no real candidate information is used anywhere in seed/tests.

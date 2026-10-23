---
inclusion: always
---

# Testing strategy

Follow test-first implementation where practical.

## Backend
Domain unit tests, rules-engine tests, state-transition tests, permission tests,
repository tests, API integration tests, migration tests, document-validation tests,
audit-event tests, privacy-workflow tests, retention tests.

## Frontend
Component tests, form-validation tests, permission-state tests, accessibility tests,
critical-workflow tests, error-handling tests.

## End-to-end
Campaign creation, JD approval, rule approval, campaign publication, candidate
application, resume upload, extraction verification, screening, human review, interview
approval, slot confirmation, interview assessment, waitlist, re-evaluation, talent-pool
consent withdrawal, candidate deletion request.

## Security
Horizontal/vertical privilege escalation, insecure object access (IDOR), malicious files,
invalid MIME, path traversal, injection, XSS, CSRF, rate limiting, token expiry, tenant
isolation, CSV injection, prompt injection in uploaded documents.

## Rules regression (must prove)
- Identical inputs + rule version => identical results.
- Rule changes create new versions; old results remain reproducible.
- Mandatory criteria behave correctly.
- Missing evidence routes correctly; low confidence routes correctly.
- Override actions require permission and reason.

## Data rule
No real candidate information in seed or test data. All synthetic data is clearly marked
synthetic.

---
inclusion: always
---

# Product — Orient Recruitment Accelerator

## What this product is

An enterprise recruitment platform organised around **Projects** (an approved hiring
need) and **Campaigns** (one position-hiring effort within a project). Each campaign
owns its own versioned Job Description (JD), versioned deterministic screening rules,
versioned scoring thresholds, and a versioned application form.

The platform runs the full hiring lifecycle: JD intake and approval, public candidate
application, safe resume processing and field extraction, deterministic eligibility
gating, explainable weighted fit scoring, human review, interview approval and walk-in
slot management, assessment, hiring decisions, waitlist, consented talent pool, and
governance (privacy, retention, audit).

## Core product principles (binding)

1. AI may extract, normalise, summarise and recommend.
2. AI must **not** make the final hiring decision.
3. Candidate rejection must **not** be based solely on an LLM output.
4. Mandatory eligibility and weighted scoring use deterministic, version-controlled rules.
5. Every score must be reproducible from stored inputs plus the stored rule version.
6. Every score component must identify its underlying candidate evidence.
7. Missing evidence is **not** automatically proof the candidate lacks a qualification.
8. Low-confidence and conflicting data must be routed to human review.
9. Threshold changes require an authorised approval and a reason.
10. Re-evaluation creates a **new** screening result and never overwrites the original.
11. Protected, medical and highly personal characteristics must not influence screening.
12. Every sensitive or consequential action must be auditable.
13. Candidate data must be minimised and protected.
14. Access must follow least privilege with object-level authorisation.
15. The product must remain usable without an LLM service.
16. The core workflow must not depend on Kiro at runtime.
17. Kiro is a development environment, not part of the production architecture.

## Primary users

HR Head, Recruitment Administrator, Recruiter, Hiring Manager, Interview Panel Member,
Management Viewer, Compliance/Audit Viewer, System Administrator, Candidate.

## MVP boundary

Authentication, RBAC, project/campaign management, JD upload and approval, JD and rule
versioning, dynamic candidate form, candidate consent, resume upload, basic PDF/DOCX
extraction, candidate verification, deterministic screening, explainable score, human
review, interview approval and invitation, slot management, waitlist, audit trail, basic
HR dashboard, Docker-based deployment, automated tests.

## Explicitly deferred (not in MVP)

Video/voice/emotion/personality/face analysis, social-media scraping, background checks,
fully automated rejection or selection, automatic threshold reduction, training on
historical hiring outcomes, unreviewed semantic ranking, public score visibility,
multi-tenant SaaS complexity, Kubernetes, microservices.

## Language rules

- Never label a person "bad candidate" or "unfit". Use outcome-oriented screening
  statuses (e.g. "Mandatory Criterion Not Confirmed", "Additional Information Required").
- Never present the product as automatically legally compliant. It provides technical
  controls that support organisational compliance.
- Never claim the system is risk-free.

# API Reference

All endpoints live under `/api/v1`. The **authoritative, always-current** reference is the
interactive OpenAPI UI at `http://localhost:8000/docs` (non-production only), where exact
request/response schemas are generated from the code and every call can be run with "Try it
out". This document is a stable, human-readable summary plus a full worked example.

- **Base URL:** `http://localhost:8000` (or go through the frontend proxy at
  `http://localhost:5173/api/...`).
- **Auth:** every authenticated call needs the header `Authorization: Bearer <access_token>`.
- **Errors:** failures return a typed envelope: `{ "error": { "code", "message",
  "correlation_id", "details? } }`.
- **Health probes (unversioned):** `GET /health`, `GET /ready`.

> All data, accounts, and credentials below are synthetic and for local evaluation only.

---

## Endpoint summary

### Identity & auth — `/api/v1`
| Method | Path                | Purpose                                  |
|--------|---------------------|------------------------------------------|
| POST   | `/auth/login`       | Exchange email+password for a token pair |
| POST   | `/auth/refresh`     | Exchange a refresh token for a new pair  |
| GET    | `/auth/me`          | Current actor: roles, permissions, scope |
| POST   | `/users`            | Create a staff user (system_admin)       |

### Projects — `/api/v1/projects`
| Method | Path            | Purpose          |
|--------|-----------------|------------------|
| POST   | ``              | Create a project |
| GET    | ``              | List projects    |
| GET    | `/{project_id}` | Get one project  |

### Campaigns — `/api/v1/campaigns`
| Method | Path                        | Purpose                                               |
|--------|-----------------------------|-------------------------------------------------------|
| POST   | ``                          | Create a campaign                                     |
| GET    | ``                          | List campaigns                                        |
| GET    | `/{campaign_id}`            | Get one campaign                                      |
| POST   | `/{campaign_id}/transition` | Drive the lifecycle state machine                     |
| POST   | `/{campaign_id}/fast-track-open` | Drive an artifact-ready campaign straight to open |
| POST   | `/{campaign_id}/assignments`| Assign a staff user to the campaign (self or by email)|
| POST   | `/{campaign_id}/rescore`    | Regenerate JD-derived criteria and re-screen every application; auto-progresses clean ≥50 candidates to the panel (campaign.edit + assignment) |
| DELETE | `/{campaign_id}`            | Hard-delete a campaign + all its data (campaign.edit, audited) |

### Job descriptions — `/api/v1/job-descriptions`
| Method | Path                                  | Purpose                                 |
|--------|---------------------------------------|-----------------------------------------|
| POST   | `/upload`                             | Upload a JD file → draft version        |
| PATCH  | `/versions/{jd_version_id}`           | Edit a draft version                    |
| POST   | `/versions/{jd_version_id}/approve`   | Approve (lock immutable)                |
| POST   | `/versions/{jd_version_id}/revise`    | Revise an approved version → new version|

### Forms — `/api/v1/forms`
| Method | Path                                   | Purpose             |
|--------|----------------------------------------|---------------------|
| POST   | `/drafts`                              | Create a form draft |
| POST   | `/versions/{form_version_id}/approve`  | Approve the form    |

### Rules — `/api/v1/rules`
| Method | Path                                        | Purpose                                                |
|--------|---------------------------------------------|--------------------------------------------------------|
| POST   | `/rule-sets/versions`                       | Create a rule-set version (manual DSL)                 |
| POST   | `/rule-sets/versions/from-jd`               | Generate a tiered scoring rule-set from the approved JD (skills + experience) |
| POST   | `/rule-sets/versions/{version_id}/approve`  | Approve (four-eyes, immutable); wires the campaign pointer |
| POST   | `/rule-sets/versions/{version_id}/reject`   | Reject a draft rule-set version                        |
| GET    | `/rule-sets/versions/pending`               | List draft rule-set versions awaiting approval         |
| POST   | `/thresholds/change`                        | Change scoring threshold (versioned); wires the campaign pointer |

**JD-derived scoring rule-set.** `POST /rule-sets/versions/from-jd` builds one combined
rule-set from the campaign's approved JD: mandatory skills → Must-Have (mandatory gate),
desirable skills → Good-to-Have (weighted), plus the JD's minimum experience as a weighted
criterion. Must-have skills that are unconfirmed route to human review; optional skills that
are absent simply score 0. Skill matching is deterministic and literal (case-insensitive,
word-boundary) with a curated alias/notation table and core-term reduction — never semantic
inference (see `extraction/skill_alias.py`, `responsible-ai.md`).

### Public apply — `/api/v1/public`  _(unauthenticated)_
| Method | Path                             | Purpose                                        |
|--------|----------------------------------|------------------------------------------------|
| GET    | `/open-roles`                    | List roles currently open for applications     |
| GET    | `/campaigns/{campaign_id}/form`  | Approved application form for an open role      |
| POST   | `/resume-preview`                | Parse an uploaded resume and return suggested form answers (read-only, nothing stored) |
| POST   | `/campaigns/{campaign_id}/apply` | Submit answers + resume (multipart)            |
| GET    | `/applications/{application_id}/status` | Coarse candidate-facing status (never exposes the raw score) |

A single consolidated careers link drives the whole candidate funnel: `/open-roles`
populates the role dropdown, `/campaigns/{id}/form` renders the approved form for the
chosen role, and `/campaigns/{id}/apply` submits it. All are rate-limitable and expose only
candidate-facing fields (no org/project ids, state, counts, or screening config) to keep
this public surface a minimal attack surface.

`POST /resume-preview` deterministically reads a resume and suggests form answers (full
name, email, mobile, experience, location, key skills) that the candidate reviews and edits
before submitting — nothing is stored and no screening runs. After a successful submission
the candidate sees a single confirmation ("Thank you for your application"); internal scores
and reviewer notes are never shown to the candidate.

### Applications — `/api/v1/applications`
| Method | Path                                                   | Purpose                              |
|--------|--------------------------------------------------------|--------------------------------------|
| POST   | `/walk-in-intake`                                      | Bulk-ingest walk-in resumes (screening.execute + assignment, consent attested) |
| GET    | `?campaign_id=...`                                     | List a campaign's applications       |
| GET    | `/{application_id}`                                    | View an application                  |
| GET    | `/{application_id}/extracted-fields`                   | List resume-extracted fields         |
| POST   | `/{application_id}/extracted-fields/{field_id}/verify` | Verify/correct a field               |

### Documents — `/api/v1/documents`
| Method | Path                                      | Purpose                              |
|--------|-------------------------------------------|--------------------------------------|
| GET    | `/applications/{application_id}/resume`   | Download a candidate's resume (authenticated, authorised) |

Resumes are **never** served from a public/bucket URL. This endpoint streams the file as an
attachment (`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`) only to an
authorised caller: staff with `candidate.view` assigned to the campaign, **or** an interview
panel member assigned to the campaign while the candidate is on the interview worklist. Only
a CLEAN (malware-scanned) document is returned. By default it returns the **original uploaded
file only** and responds `404` when the original is unavailable — so extracted text is never
passed off as the original. A caller that deliberately wants the extracted resume text (the
interview-panel read-only preview) may pass `?fallback=text`, which returns the extracted
text clearly labelled as such (distinct filename + `X-Resume-Source: extracted-text-fallback`
header). The Recruiter/HR Applications tab, the in-app report preview, and the Excel
workbook all expose this as a per-candidate **Download résumé** action/link (shown only to
users with `candidate.view` + campaign assignment); an unavailable resume shows
**Resume unavailable**, never a broken link.

### Candidates — `/api/v1/candidates`
| Method | Path                                   | Purpose                                             |
|--------|----------------------------------------|-----------------------------------------------------|
| GET    | `/{candidate_id}`                      | Candidate profile with contact PII **masked** (candidate.view) |
| GET    | `/{candidate_id}/contact`              | Reveal unmasked contact PII — elevated candidate.view_pii, audited |
| POST   | `/{candidate_id}/talent-pool/withdraw` | Withdraw from talent pool (204)                     |

### Screening — `/api/v1/screening`
| Method | Path                                   | Purpose                                |
|--------|----------------------------------------|----------------------------------------|
| POST   | `/applications/{application_id}/run`   | Run deterministic screening            |
| GET    | `/applications/{application_id}/runs`  | List immutable screening runs          |

### Reviews — `/api/v1/reviews`
| Method | Path                          | Purpose                                   |
|--------|-------------------------------|-------------------------------------------|
| GET    | `?campaign_id=...`            | List review items for a campaign          |
| POST   | `/{review_item_id}/actions`   | Record a review action (advance/hold/...) |

### Interviews — `/api/v1/interviews`
| Method | Path                                       | Purpose                     |
|--------|--------------------------------------------|-----------------------------|
| POST   | `/stages`                                  | Create an interview stage   |
| POST   | `/slots`                                   | Create a time slot          |
| POST   | `/invitations/approve`                     | Approve an invitation (optional `reason`; **required** when the candidate is under review / below the 50% bar) |
| POST   | `/invitations/walk-in`                     | Select-for-interview express path: approve + auto-schedule in one call, placing the candidate on the Interview Panel. `reason` **required** for below-threshold candidates (recorded as a screening override) |
| POST   | `/invitations/{invitation_id}/assign-slot` | Assign a slot to invitation |
| POST   | `/invitations/{invitation_id}/attendance`  | Record attendance — **Interview Panel** (assessment.submit, assigned to the campaign), not the scheduling recruiter |
| POST   | `/invitations/{invitation_id}/check-in`    | Interview-day check-in — Interview Panel, assigned to the campaign |
| POST   | `/invitations/{invitation_id}/check-out`   | Interview-day check-out (after assessment) — Interview Panel, assigned to the campaign |
| GET    | `/campaigns/{campaign_id}/assignments`     | List interviewer assignments for a campaign (metadata only); `interview.assign` |
| POST   | `/campaigns/{campaign_id}/assignments`     | Assign an interviewer to the campaign (optional `stage_id`); idempotent; `interview.assign` |
| PATCH  | `/assignments/{assignment_id}`             | Change an assignment's stage scope; `interview.assign` |
| DELETE | `/assignments/{assignment_id}`             | Soft-remove an assignment (preserves submitted assessments); `interview.assign` |
| GET    | `/my-assignments`                          | The authenticated interviewer's own assignment buckets (campaign id + label); `assessment.submit` |

Candidates scoring **≥ 50%** are placed on the Interview Panel automatically on submit.
A Recruitment Admin can still **Select for interview** a below-50 (under-review) candidate
from the Applications/Interviews view; that is a screening override and requires a recorded
`reason`, which is written to the audit trail.

**Interviewer assignment & isolation.** `interview.assign` (System Admin org-wide, Recruiter
Admin for campaigns it manages) controls which panel members interview which campaign/stage.
A panel member only sees and can act on candidates for jobs (and stages) they are assigned
to; the assignment endpoints expose assignment metadata only — never candidate profiles,
resumes, scores, or scorecards. See `docs/permission-matrix.md` → *Interviewer assignment &
panel isolation*.

### Assessments — `/api/v1/assessments`  _(Interview Panel)_
| Method | Path          | Purpose                                                      |
|--------|---------------|--------------------------------------------------------------|
| GET    | `/panel`      | The panel member's own dashboard: to-attend / to-assess / completed counts + list. Scoped to the member's active assignments; optional `?campaign_id=` narrows to one assigned job bucket (by stable UUID) |
| GET    | `/assignable` | Candidates who attended and await this panel member's assessment (only for campaigns they are assigned to) |
| POST   | ``            | Submit an interview assessment/score (only for an assigned candidate)        |

**Attendance belongs to the Interview Panel.** Marking a candidate attended / no-show is
done by the panel (permission `assessment.submit`), not by the recruiter who scheduled the
interview — recruiters create stages and slots but never confirm who showed up. The panel
dashboard surfaces each invited interview, lets the member mark attendance, and then
(once attended) collects the assessment. See `docs/state-machines.md`.

**Panel isolation.** The panel worklist and assessment submission are restricted to
candidates for jobs (and stages) the authenticated interviewer is assigned to (see
*Interviewer assignment* above). A member with no assignment gets an empty worklist; buckets
are keyed by stable campaign UUID so two jobs with the same title never merge.

### Decisions — `/api/v1/decisions`
| Method | Path        | Purpose                                                       |
|--------|-------------|---------------------------------------------------------------|
| GET    | `/pending`  | Assessed candidates awaiting a hiring decision, with the panel's assessment(s) (hiring_decision.recommend) |
| GET    | `/outcomes` | Decided candidates (selected / rejected / hold) with reasons (candidate.view) |
| POST   | ``          | Record a hiring decision (select/reject require hiring_decision.approve) |

### Waitlist — `/api/v1/waitlist`
| Method | Path          | Purpose                        |
|--------|---------------|--------------------------------|
| POST   | ``            | Add a candidate to the waitlist|
| POST   | `/reevaluate` | Re-evaluate the waitlist       |

### Talent pool — `/api/v1/talent-pool`
| Method | Path                | Purpose              |
|--------|---------------------|----------------------|
| GET    | `/search?skill=...` | Search by skill      |

### Privacy — `/api/v1/privacy`
| Method | Path                              | Purpose                        |
|--------|-----------------------------------|--------------------------------|
| POST   | `/requests`                       | Create a privacy request (DSAR)|
| POST   | `/requests/{request_id}/complete` | Complete a privacy request     |
| POST   | `/retention-policies`             | Set a retention policy         |

### Reports — `/api/v1/reports`
| Method | Path                                   | Purpose                        |
|--------|----------------------------------------|--------------------------------|
| GET    | `/hr-dashboard`                        | HR operational dashboard       |
| GET    | `/management-dashboard`                | Aggregated management metrics  |
| GET    | `/campaigns/{campaign_id}/report`      | **In-app report preview** (JSON): the same candidate records the Excel download contains, for the on-screen preview table; `candidate.view` + campaign assignment |
| GET    | `/campaigns/{campaign_id}/export`      | Download the HR `.xlsx` of every candidate in a campaign using the **saved** scores/ranks (no rescoring); `candidate.view` + campaign assignment |

**One shared report model.** Both the JSON preview (`/report`) and the `.xlsx` download
(`/export`) are built from a single `report_builder.build_campaign_report` model, so the
in-app **Preview Excel** table and the downloaded workbook always show identical candidate
records (same rows, same order). Read-only: both reuse the saved screening ranking
(`list_ranked_for_campaign`); nothing is recomputed and no records are mutated.

The workbook is an HR-focused **two-sheet** file:

- **Candidates** — one decision-relevant row per candidate: Rank, Candidate name, Email
  address, Contact number, Applied position, Application status, **Overall score (%)**,
  **JD skills match (%)**, Relevant skills & experience, Key strengths, Missing / unverified
  requirements, a **Download Resume** hyperlink, and a **Candidate summary** hyperlink.
  Frozen header row, autofilter, sensible column widths.
- **Summary** — campaign facts and a short legend distinguishing the two scores.

Scores and derived fields (never invented):

- **Overall score** is the saved deterministic fit score (`ScreeningRun.score`, 0–100%).
- **JD skills match %** is *derived* from the JD skill criteria only (`criterion_type ==
  "exact_skill"`, awarded ÷ max); it shows "Not provided" when a run has no skill criteria.
  It is a distinct number from the overall score and always labelled as derived.
- **Relevant skills / key strengths** and **missing / unverified requirements** are derived
  from the saved `CriterionResult` rows (pass → strength/skill; must-have fail → missing
  requirement; `manual_review` → needs human verification). No stored fields are invented.

Internal IDs (application/candidate UUIDs) and technical metadata (rule-set/engine versions,
hashes) are **not** shown as columns — an application id appears only inside the
authenticated resume/summary hyperlink targets.

Contact PII: email/phone are **masked** unless the caller holds `candidate.view_pii`, in
which case the report routes through the audited `candidates.service.reveal_contact` (every
reveal is logged) and shows the real values. All untrusted text is neutralised against
spreadsheet-formula injection; the `.xlsx` is served as an attachment with
`X-Content-Type-Options: nosniff`. The hyperlinks point at authenticated SPA routes
(`{app_base_url}/resume/{id}` and `{app_base_url}/campaigns/{campaign}/candidates/{id}`),
never a public/bucket URL; `app_base_url` is configurable via `ORA_APP_BASE_URL` for
deployed environments.

### Audit — `/api/v1/audit`
| Method | Path | Purpose                           |
|--------|------|-----------------------------------|
| GET    | ``   | List hash-chained audit events    |

---

## Worked example (every endpoint, in workflow order)

Replace `<...>` placeholders with ids returned by the preceding call. Exact body field
names are enforced by the Pydantic schemas; confirm them in `/docs`.

### Authenticate

```bash
# Log in and capture the token
curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"synthetic.recruiter_admin@example.com","password":"SyntheticDevPassword123"}'
# -> { "access_token": "...", "refresh_token": "...", "token_type": "bearer" }
TOKEN="<access_token>"

curl -s http://localhost:8000/api/v1/auth/me -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/v1/auth/refresh \
  -H "Content-Type: application/json" -d '{"refresh_token":"<refresh_token>"}'

# system_admin creates a staff user
curl -s -X POST http://localhost:8000/api/v1/users \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"email":"new.reviewer@example.com","password":"SyntheticDevPassword123","role_names":["recruiter"]}'
```

### Project & campaign

```bash
curl -s -X POST http://localhost:8000/api/v1/projects \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"Backend Hiring 2026","description":"Platform team"}'
PROJECT_ID="<id>"

curl -s http://localhost:8000/api/v1/projects -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/v1/projects/$PROJECT_ID -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/v1/campaigns \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"project_id\":\"$PROJECT_ID\",\"name\":\"Senior Python Engineer 2026\",\"position_title\":\"Senior Python Engineer\",\"number_of_openings\":2,\"employment_type\":\"full_time\",\"work_mode\":\"hybrid\"}"
CAMPAIGN_ID="<id>"

curl -s http://localhost:8000/api/v1/campaigns -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/v1/campaigns/$CAMPAIGN_ID -H "Authorization: Bearer $TOKEN"

# Drive the lifecycle (see docs/state-machines.md for valid target states).
# Every transition requires a destination AND a reason (audited).
curl -s -X POST http://localhost:8000/api/v1/campaigns/$CAMPAIGN_ID/transition \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"destination":"configuring","reason":"Begin JD/rules setup"}'

# Shortcut: once all five artifacts (JD, form, rules, threshold, privacy notice) are
# approved, drive straight to open in one audited action.
curl -s -X POST http://localhost:8000/api/v1/campaigns/$CAMPAIGN_ID/fast-track-open \
  -H "Authorization: Bearer $TOKEN"

# Assign a staff user to the campaign (self-assign when email is omitted).
curl -s -X POST http://localhost:8000/api/v1/campaigns/$CAMPAIGN_ID/assignments \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"email":"synthetic.recruiter@example.com"}'

# Hard-delete a campaign and all its data (campaign.edit + assignment; audited).
curl -s -X DELETE http://localhost:8000/api/v1/campaigns/$CAMPAIGN_ID \
  -H "Authorization: Bearer $TOKEN"
```

### Job description (immutable versions)

```bash
curl -s -X POST http://localhost:8000/api/v1/job-descriptions/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "campaign_id=$CAMPAIGN_ID" -F "file=@jd.pdf;type=application/pdf"
JD_VERSION_ID="<id>"

curl -s -X PATCH http://localhost:8000/api/v1/job-descriptions/versions/$JD_VERSION_ID \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"Updated JD text, 5+ years Python."}'

curl -s -X POST http://localhost:8000/api/v1/job-descriptions/versions/$JD_VERSION_ID/approve \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/v1/job-descriptions/versions/$JD_VERSION_ID/revise \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"content":"v2: added Kubernetes requirement."}'
```

### Application form

```bash
curl -s -X POST http://localhost:8000/api/v1/forms/drafts \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"campaign_id\":\"$CAMPAIGN_ID\",\"form_schema\":{\"fields\":[{\"key\":\"years_experience\",\"type\":\"number\",\"label\":\"Years of experience\"}]}}"
FORM_VERSION_ID="<id>"

curl -s -X POST http://localhost:8000/api/v1/forms/versions/$FORM_VERSION_ID/approve \
  -H "Authorization: Bearer $TOKEN"
```

### Rules & threshold (four-eyes: approve as a different account)

The recommended path is to generate the scoring rule-set straight from the approved JD —
tiered skills (mandatory → Must-Have gate, desirable → Good-to-Have weighted) plus the
JD's minimum experience as a weighted criterion. You can also author a rule-set by hand.

```bash
# Preferred: generate from the campaign's approved JD (no body beyond campaign_id)
curl -s -X POST http://localhost:8000/api/v1/rules/rule-sets/versions/from-jd \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"campaign_id\":\"$CAMPAIGN_ID\"}"
RULESET_VERSION_ID="<id>"

# Alternative: author a rule-set version by hand (typed JSON DSL)
curl -s -X POST http://localhost:8000/api/v1/rules/rule-sets/versions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"campaign_id\":\"$CAMPAIGN_ID\",\"name\":\"Senior Python v1\",\"rules\":[{\"id\":\"exp\",\"when\":{\">=\":[{\"var\":\"years_experience\"},5]},\"score\":40}]}"

# List drafts awaiting approval, then approve as a DIFFERENT user (separation of duties).
curl -s http://localhost:8000/api/v1/rules/rule-sets/versions/pending \
  -H "Authorization: Bearer $APPROVER_TOKEN"

curl -s -X POST http://localhost:8000/api/v1/rules/rule-sets/versions/$RULESET_VERSION_ID/approve \
  -H "Authorization: Bearer $APPROVER_TOKEN"   # different user than author

# Or reject a draft with a reason
curl -s -X POST http://localhost:8000/api/v1/rules/rule-sets/versions/$RULESET_VERSION_ID/reject \
  -H "Authorization: Bearer $APPROVER_TOKEN" -H "Content-Type: application/json" \
  -d '{"change_reason":"Experience criterion too strict for this market."}'

# Threshold change is itself four-eyes: approver_id must differ from the caller.
curl -s -X POST http://localhost:8000/api/v1/rules/thresholds/change \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"campaign_id\":\"$CAMPAIGN_ID\",\"review_below\":50,\"recommend_at_or_above\":60,\"change_reason\":\"Calibrated to headcount\",\"approver_id\":\"<other_user_id>\"}"
```

Then transition the campaign to its published/open state so candidates can apply.

### Public application (no auth)

```bash
curl -s -X POST http://localhost:8000/api/v1/public/campaigns/$CAMPAIGN_ID/apply \
  -F 'answers={"years_experience":7,"full_name":"Alex Doe","email":"alex@example.com"}' \
  -F "resume=@alex_resume.pdf;type=application/pdf"
# -> { "application_id": "...", "state": "...", "manual_review": false, "message": "..." }
APPLICATION_ID="<application_id>"
```

### Review extracted fields

```bash
curl -s http://localhost:8000/api/v1/applications/$APPLICATION_ID -H "Authorization: Bearer $TOKEN"

curl -s http://localhost:8000/api/v1/applications/$APPLICATION_ID/extracted-fields \
  -H "Authorization: Bearer $TOKEN"
FIELD_ID="<id>"

curl -s -X POST \
  http://localhost:8000/api/v1/applications/$APPLICATION_ID/extracted-fields/$FIELD_ID/verify \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"verified_value":"7","verified":true}'
```

### Candidates & talent pool

```bash
# Profile with contact PII MASKED (candidate.view).
curl -s http://localhost:8000/api/v1/candidates/$CANDIDATE_ID -H "Authorization: Bearer $TOKEN"

# Reveal unmasked contact details — elevated candidate.view_pii; every reveal is audited.
curl -s http://localhost:8000/api/v1/candidates/$CANDIDATE_ID/contact -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/v1/candidates/$CANDIDATE_ID/talent-pool/withdraw \
  -H "Authorization: Bearer $TOKEN"   # 204 No Content
```

### Screening (deterministic, reproducible)

```bash
curl -s -X POST http://localhost:8000/api/v1/screening/applications/$APPLICATION_ID/run \
  -H "Authorization: Bearer $TOKEN"

curl -s http://localhost:8000/api/v1/screening/applications/$APPLICATION_ID/runs \
  -H "Authorization: Bearer $TOKEN"
```

### Review queue

```bash
curl -s "http://localhost:8000/api/v1/reviews?campaign_id=$CAMPAIGN_ID" \
  -H "Authorization: Bearer $TOKEN"
REVIEW_ITEM_ID="<id>"

curl -s -X POST http://localhost:8000/api/v1/reviews/$REVIEW_ITEM_ID/actions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"advance","note":"Strong match, move to interview."}'
```

### Interviews

```bash
curl -s -X POST http://localhost:8000/api/v1/interviews/stages \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"campaign_id\":\"$CAMPAIGN_ID\",\"name\":\"Technical Round\",\"sequence\":1}"
STAGE_ID="<id>"

curl -s -X POST http://localhost:8000/api/v1/interviews/slots \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"stage_id\":\"$STAGE_ID\",\"starts_at\":\"2026-10-20T10:00:00Z\",\"ends_at\":\"2026-10-20T11:00:00Z\"}"
SLOT_ID="<id>"

curl -s -X POST http://localhost:8000/api/v1/interviews/invitations/approve \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"application_id\":\"$APPLICATION_ID\",\"stage_id\":\"$STAGE_ID\"}"
INVITATION_ID="<id>"

curl -s -X POST http://localhost:8000/api/v1/interviews/invitations/$INVITATION_ID/assign-slot \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"slot_id\":\"$SLOT_ID\"}"

# Attendance is confirmed by the INTERVIEW PANEL, not the recruiter who scheduled it.
# Use a panel member's token (assessment.submit).
curl -s -X POST http://localhost:8000/api/v1/interviews/invitations/$INVITATION_ID/attendance \
  -H "Authorization: Bearer $PANEL_TOKEN" -H "Content-Type: application/json" \
  -d '{"attended":true}'
```

### Assessments (Interview Panel) & decision

The panel member works from their own dashboard, confirms attendance (above), then submits
the assessment. Both use the panel member's token.

```bash
# The panel member's worklist: to-attend / to-assess / completed, with counts.
curl -s http://localhost:8000/api/v1/assessments/panel -H "Authorization: Bearer $PANEL_TOKEN"
curl -s http://localhost:8000/api/v1/assessments/assignable -H "Authorization: Bearer $PANEL_TOKEN"

# Submit the assessment (structured criteria scores + a recommendation, not a single number).
curl -s -X POST http://localhost:8000/api/v1/assessments \
  -H "Authorization: Bearer $PANEL_TOKEN" -H "Content-Type: application/json" \
  -d "{\"application_id\":\"$APPLICATION_ID\",\"recommendation\":\"recommend\",\"criteria_scores\":{\"system_design\":4,\"coding\":5},\"interview_notes\":\"Strong on system design.\"}"

# Hiring decision. The decision maker reviews pending (assessed) candidates first.
curl -s http://localhost:8000/api/v1/decisions/pending -H "Authorization: Bearer $TOKEN"

# select/reject require hiring_decision.approve; hold/withdraw require hiring_decision.recommend.
curl -s -X POST http://localhost:8000/api/v1/decisions \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"application_id\":\"$APPLICATION_ID\",\"decision_type\":\"select\",\"reason\":\"Top candidate.\"}"

# Review decided candidates (selected / rejected / hold) with reasons.
curl -s http://localhost:8000/api/v1/decisions/outcomes -H "Authorization: Bearer $TOKEN"
```

### Waitlist, talent pool, privacy

```bash
curl -s -X POST http://localhost:8000/api/v1/waitlist \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"application_id\":\"$APPLICATION_ID\",\"campaign_id\":\"$CAMPAIGN_ID\"}"

curl -s -X POST http://localhost:8000/api/v1/waitlist/reevaluate \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"campaign_id\":\"$CAMPAIGN_ID\"}"

curl -s "http://localhost:8000/api/v1/talent-pool/search?skill=python" \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/v1/privacy/requests \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"candidate_id\":\"$CANDIDATE_ID\",\"request_type\":\"erasure\"}"
PRIVACY_REQUEST_ID="<id>"

curl -s -X POST http://localhost:8000/api/v1/privacy/requests/$PRIVACY_REQUEST_ID/complete \
  -H "Authorization: Bearer $TOKEN"

curl -s -X POST http://localhost:8000/api/v1/privacy/retention-policies \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"category":"rejected_applications","retention_days":180}'
```

### Reporting & audit

```bash
curl -s http://localhost:8000/api/v1/reports/hr-dashboard -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/v1/reports/management-dashboard -H "Authorization: Bearer $TOKEN"
curl -s http://localhost:8000/api/v1/audit -H "Authorization: Bearer $TOKEN"
```

---

_All example data, accounts, and credentials are synthetic and for local evaluation only._

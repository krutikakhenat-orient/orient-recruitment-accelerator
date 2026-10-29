# Permission Matrix

Permissions are fine-grained and bundled into roles (see
`backend/app/modules/identity/permissions.py`, the source of truth). On top of a permission
check, an **object-level** check normally confirms the actor is assigned to the specific
campaign/application (`CampaignAssignment`). Candidates are modelled separately and do not
hold staff permissions.

## Operational roles (3-tier model)

The day-to-day staff roles are three:

- **Recruiter** — authors the hiring setup (project, campaign, JD, screening rules,
  thresholds, form) and runs the operational work (screening, scheduling, review, waitlist,
  talent-pool search). Holds **no approval authority**: the Recruiter proposes, someone else
  signs off.
- **Recruiter Admin** — everything the Recruiter does **plus** all approval/sign-off
  authorities **plus** the former Hiring Manager duties (JD approval, candidate review,
  interview approval, hiring recommend/approve, audited PII reveal). This single role is the
  recruitment-governance tier. It deliberately does **not** hold system administration.
- **Interview Panel** — restricted to the interview they are invited to: confirm attendance
  and submit a structured assessment. Holds only `assessment.submit`.

The former **HR Head** and **Hiring Manager** roles were consolidated into **Recruiter
Admin**. The remaining non-operational roles (Management Viewer, Audit Viewer, System Admin,
Candidate) are retained for governance/public use.

## Object-level exceptions (not campaign-scoped)

Two application-state transitions are checked with a **global** permission only, because the
actor performing them (an Interview Panel member) is invited to a specific candidate and is
deliberately **not** a campaign assignee. The application state scopes the action instead;
both are marked `campaign_scoped=False` in `backend/app/modules/applications/states.py`:

- `interview_scheduled → attended` / `interview_scheduled → no_show` — attendance is
  recorded by the **Interview Panel** (`assessment.submit`). *(Changed: attendance was
  previously a Recruiter/Recruiter-Admin action under `interview.schedule`.)*
- `attended → assessed` — assessment submission (`assessment.submit`).

See [state-machines.md](state-machines.md).

Legend: ● granted by default to the role.

| Permission | Recruiter | Recruiter Admin | Interview Panel | Mgmt View | Audit View | Sys Admin |
|---|:--:|:--:|:--:|:--:|:--:|:--:|
| project.create | ● | ● | | | | |
| campaign.create | ● | ● | | | | |
| campaign.edit | ● | ● | | | | |
| campaign.approve | | ● | | | | |
| campaign.publish | | ● | | | | |
| campaign.pause | | ● | | | | |
| jd.upload | ● | ● | | | | |
| jd.review | ● | ● | | | | |
| jd.approve | | ● | | | | |
| rule.create | ● | ● | | | | |
| rule.approve | | ● | | | | |
| threshold.change | | ● | | | | |
| candidate.view | ● | ● | | | | |
| candidate.view_pii | | ● | | | | |
| candidate.correct | ● | ● | | | | |
| application.review | ● | ● | | | | |
| screening.execute | ● | ● | | | | |
| interview.approve | | ● | | | | |
| interview.schedule | ● | ● | | | | |
| interview.assign | | ● | | | | ● |
| assessment.submit | | | ● | | | |
| hiring_decision.recommend | | ● | | | | |
| hiring_decision.approve | | ● | | | | |
| waitlist.manage | ● | ● | | | | |
| talent_pool.search | ● | ● | | | | |
| audit.view | | | | | ● | |
| privacy_request.manage | | | | | | ● |
| user.manage | | | | | | ● |
| system.configure | | | | | | ● |

> Note: attendance (`interview_scheduled → attended/no_show`) is performed by the Interview
> Panel via `assessment.submit`; it has no dedicated permission column. Recruiter Admin
> schedules interviews but does not mark attendance.

## Separation-of-duties rules (enforced in domain policy/service)
- The creator of a rule set cannot be its sole approver (`rules/service.approve_rule_set_version`).
  In practice a **Recruiter** authors and a **different Recruiter Admin** approves (four-eyes).
- Threshold changes require a distinct approver when four-eyes is configured
  (`rules/service.change_threshold`).
- Interview panel members hold only `assessment.submit` — they cannot alter rules or screen.
  They are now scoped to candidates for jobs (and, when set, stages) they are **assigned**
  to via an `InterviewAssignment` (see Interviewer assignment below); with no assignment a
  panel member sees an empty worklist.
- `interview.assign` governs **who** interviews a job. It is an administrative grant over
  assignment metadata only — it confers **no** candidate-content access (no `candidate.view`,
  resumes, scores, or scorecards). Held by **Recruiter Admin** (object-level: only campaigns
  it is assigned to) and **System Admin** (organisation-wide assignment management).
- Management viewers and audit viewers are read-only; audit viewers see only audit data.
- System administrators get no automatic candidate-content access; such access must be
  explicitly authorised and is logged. Granting `interview.assign` to System Admin lets them
  manage interviewer assignments **without** gaining candidate-content access.
- Unmasking candidate contact PII (`candidate.view_pii`) is a distinct grant held only by
  Recruiter Admin and is audited on every reveal.

## Interviewer assignment & panel isolation
Interview-panel access is object-level, governed by the `interview_assignment` table (the
interview analogue of `campaign_assignment`):

- An `InterviewAssignment` links an interviewer (a user holding `assessment.submit`) to a
  campaign and, optionally, an interview stage (`stage_id = NULL` means the whole campaign).
- A panel member's worklist and **every** interview-day action — reading a candidate's
  resume/application/extracted fields, check-in, check-out, attendance, and assessment
  submission — are scoped to their active assignments by stable campaign UUID (never by
  campaign display name). No assignment ⇒ empty worklist and denied actions; a stage-scoped
  assignment grants access to that stage only. Deactivating an assignment revokes access on
  the next request.
- Isolation is enforced in the **backend services** (not just the UI); a forged application
  id from an unassigned campaign is refused, so an interviewer cannot reach another role's
  candidates by changing an id.
- Assignments are managed through `POST/GET /api/v1/interviews/campaigns/{id}/assignments`,
  `PATCH/DELETE /api/v1/interviews/assignments/{id}`, gated by `interview.assign` plus
  management authorisation (System Admin org-wide; Recruiter Admin for campaigns it manages).
  Create/update/remove emit audit events; removal is a soft-deactivate that preserves
  submitted assessments and history.
- Independent scorecards are unchanged: each interviewer's assessment is keyed by
  `(application_id, panel_member_id)`; one interviewer never overwrites another's.

## Candidate (public)
Candidates are not staff. They apply via the public portal (the consolidated `/apply` page
or a direct `/apply/<campaign_id>` link), confirm/correct their extracted data, and manage
consent (including talent-pool withdrawal). They never see internal scores, reviewer notes,
or other candidates.

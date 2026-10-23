# State Machines

Both machines are enforced by a single transition service each; transitions not listed are
rejected. Source of truth: `backend/app/modules/campaigns/states.py` and
`backend/app/modules/applications/states.py`.

## Campaign lifecycle

| From | To | Permission | Required prerequisites |
|---|---|---|---|
| draft | jd_uploaded | jd.upload | validated JD document |
| jd_uploaded | jd_review | jd.review | extracted JD draft |
| jd_review | criteria_configuration | jd.approve | approved JD version |
| criteria_configuration | criteria_review | rule.create | rule-set draft |
| criteria_review | approval_pending | rule.approve | approved rule-set version |
| approval_pending | approved | campaign.approve | JD + rule-set + form + threshold + privacy notice |
| approved | published | campaign.publish | all of the above (AC-04) |
| published | applications_open | campaign.publish | — |
| applications_open | applications_closed / paused | campaign.pause | reason |
| paused | applications_open | campaign.pause | reason |
| applications_closed | screening | screening.execute | — |
| screening | human_review | application.review | review items generated |
| human_review | interview_planning | interview.approve | invitation approval |
| interview_planning | interviewing | interview.schedule | slots assigned |
| interviewing | selection_review | assessment.submit | assessments present |
| selection_review | completed | hiring_decision.approve | decision approved |
| completed | closed → archived | campaign.edit | — |
| draft/jd_uploaded/jd_review/criteria_*/approval_pending | cancelled | campaign.edit | reason |

## Application / candidate disposition

| From | To | Permission | Notes |
|---|---|---|---|
| submitted | documents_processing | (system) | after submission |
| documents_processing | extraction_review | (system) | extraction complete |
| extraction_review | screened | screening.execute | screening run (also auto-on-submit — see note) |
| screened | manual_review | application.review | reviewer opens |
| manual_review | screened | application.review | reviewer resolves |
| manual_review | additional_info_requested | application.review | candidate comms |
| additional_info_requested | documents_processing | (system) | resubmission |
| screened | interview_recommended | interview.approve | AC-14 |
| screened / manual_review | waitlisted | waitlist.manage | |
| interview_recommended | interview_scheduled | interview.schedule | slot confirmed |
| interview_scheduled | attended / no_show | assessment.submit | attendance — **recorded by the Interview Panel, not campaign-scoped** (see note) |
| attended | assessed | assessment.submit | **not campaign-scoped** — see note |
| assessed | selected / rejected | hiring_decision.approve | candidate comms |
| assessed | hold | hiring_decision.recommend | |
| (most pre-decision states) | withdrawn | (candidate) | candidate comms |

Any transition not in these tables raises `invalid_transition` (HTTP 409).

### Automated screening on submit

When a campaign already has an approved rule-set, the submission flow runs deterministic
screening automatically (`extraction_review → screened`) so a result is waiting for staff
with no manual trigger (`applications/service.submit_application` →
`screening.auto_screen_on_submit`). This never auto-rejects or auto-invites: borderline,
low-confidence, missing-evidence, or conflicting cases route to the human Review Queue. If
no rule-set is approved yet, screening is deferred and staff run it later via
`screening.execute`. The transition and its guarantees are identical in both paths.

### Object-level scoping of application transitions

By default, a user-permissioned transition requires the actor to **both** hold the
permission **and** be assigned to the campaign (`require_campaign_permission`). Each
transition carries a `campaign_scoped` flag (default `True`) in
`backend/app/modules/applications/states.py` to control this.

The exceptions are the two **Interview Panel** transitions, both `campaign_scoped=False` and
both gated on the global `assessment.submit` permission:

- **`interview_scheduled → attended` / `→ no_show`** — the panel confirms attendance.
- **`attended → assessed`** — the panel submits the assessment.

Interview panel members are invited to a specific candidate they interviewed and are
deliberately **not** campaign assignees. For these transitions the service checks the global
`assessment.submit` permission only; the source state (`interview_scheduled` / `attended`)
scopes the action to genuinely-scheduled/interviewed candidates. All other object-level
guarantees are unchanged.

> **Change note (role refactor):** attendance was previously recorded by a
> Recruiter/Recruiter Admin under `interview.schedule` and was campaign-scoped. It is now an
> Interview Panel action (`assessment.submit`, not campaign-scoped), so the panel owns the
> candidate end-to-end from attendance through assessment. The Recruiter Admin still
> approves and schedules interviews but no longer marks attendance. The walk-in express path
> (`interviews/service.record_walk_in_interview`) now stops at `interview_scheduled` and
> hands off to the panel rather than auto-marking attendance.

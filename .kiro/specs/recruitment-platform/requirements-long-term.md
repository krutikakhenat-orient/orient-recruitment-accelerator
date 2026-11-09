# Requirements (Long-Term Plan) — Recruitment & Onboarding Automation

**Status:** Draft v0.1 · **Date:** 2026-11-07 · **Owner:** Product / HR Technology
**Companion documents:** [requirements.md](requirements.md) (MVP, Requirements 1–16),
[design.md](design.md), [tasks.md](tasks.md), and the Business Requirements Document
[docs/BRD.md](../../../docs/BRD.md).

## Purpose

This file records the **long-term** AI and automation requirements for the HR Recruitment
and Onboarding processes. It extends the MVP in `requirements.md` and **does not change it**.
Requirement numbering continues from 17. The MVP acceptance gate (AC-01..AC-25) is
unaffected; long-term acceptance criteria are LT-AC-01.. at the end of this file.

The goal of this plan is to find where automation adds real value by **removing manual
work, shortening turnaround time, reducing follow-ups, and improving process tracking**.

## Source

The 20 use cases below were consolidated from stakeholder discussion (HR / Orient
Technologies) and are reproduced verbatim in [docs/BRD.md, Appendix A](../../../docs/BRD.md).
Each is traced to a requirement here using the IDs **UC-R01..UC-R11** (Recruitment) and
**UC-O01..UC-O09** (Onboarding).

| UC ID | Use case | Requirement | Phase |
|---|---|---|---|
| UC-R01 | Resume–JD matching & candidate shortlisting | 17 | Enhance existing |
| UC-R02 | Resume information extraction | 18 | Enhance existing |
| UC-R03 | AI-based preliminary screening | 19 | Enhance existing |
| UC-R04 | Interview scheduling automation | 20 | B |
| UC-R05 | Candidate WhatsApp/email reminders | 21 | A |
| UC-R06 | Candidate confirmation & interviewer notification | 22 | A |
| UC-R07 | Interview feedback summarisation | 23 | B |
| UC-R08 | Recruitment SLA monitoring & follow-up | 24 | A |
| UC-R09 | Naukri/NOCR & other sourcing integration | 25 | 0 → E |
| UC-R10 | Offer & post-selection follow-ups | 26 | B |
| UC-R11 | Post-selection document collection & verification | 27, 28 | C, D |
| UC-O01 | Automated document collection | 27 | C |
| UC-O02 | Document submission reminders | 27 | C |
| UC-O03 | AI-based document verification | 28 | D |
| UC-O04 | Pre-joining reminders | 29 | C |
| UC-O05 | AI avatar-based induction | 30 | 0 → E |
| UC-O06 | Policy & department SOP distribution | 31 | C |
| UC-O07 | HR text assistant / chatbot | 32 | D |
| UC-O08 | ZingHR integration | 33 | 0 → E |
| UC-O09 | Automated welcome communication | 34 | C |

**Phases:** 0 = time-boxed feasibility spike; A = notification and SLA foundation;
B = scheduling, feedback and offer; C = onboarding core; D = AI-assisted verification and
HR assistant; E = external integrations.

## Baseline (what exists today)

Stated so requirements describe the *delta*. Based on a code review on 2026-11-07; verify
before planning delivery.

| Capability | Baseline |
|---|---|
| Matching / rules | Deterministic typed-JSON rules, weighted scoring, thresholds, explainable runs (Req 7, 8). |
| Extraction | PDF/DOCX/OCR resume extraction, JD extractor, skill alias table, human verification (Req 3, 5, 6). |
| AI preliminary interview | `ai_interviews` module with a voice interview agent (single-use candidate link). |
| Interviews | Stages, slots with capacity, invitations, panel assignment, check-in/check-out, assessments (Req 10). No interviewer/candidate availability matching and no calendar integration. |
| Notifications | Specified in Req 12.1 and design.md, **not implemented** (task 5.5 open). MailHog is provisioned in dev only. |
| Hiring decisions | Select / reject / hold / withdraw workflow (Req 10.4). No offer or onboarding workflow. |
| Induction | One developer-seeded induction video, completion record and certificate for the `employee` role. |
| Assistant | Rule-based "Orient HR Assistance" for recruiter how-to questions. Not an employee HR-policy assistant. |
| SLA / escalation | None. |
| External integrations | None. |

## Guardrails that apply to every requirement below

These restate binding product rules (steering: `product.md`, `responsible-ai.md`,
`privacy.md`, `security.md`) so each long-term feature inherits them.

- **G1 — AI never decides.** AI may extract, normalise, summarise and recommend. No hiring,
  offer, rejection or onboarding-clearance decision is made or triggered by AI output.
- **G2 — Deterministic fallback.** Every AI-assisted feature SHALL work, in reduced form,
  with the LLM adapter disabled (`ORA_LLM_ADAPTER_ENABLED=false`).
- **G3 — Human in the loop.** Verification flags and summaries are advisory; a named user
  confirms or overrides, with reason, and the action is audited.
- **G4 — Missing evidence is not proof of absence.** Missing or inconsistent data routes to
  human review; it never auto-disqualifies.
- **G5 — Documents are untrusted input.** Existing upload, quarantine, scanning and
  prompt-injection defences apply to every new document type.
- **G6 — Data minimisation and purpose limitation.** Onboarding data is collected only after
  selection, for onboarding purposes, and is never visible to or used by screening.
- **G7 — No prohibited inference.** No personality, emotion, face, voice-stress, medical or
  appearance-based inference (steering: `responsible-ai.md`).
- **G8 — Candidate communications never expose internal scores or recruiter notes** (AC-15).
- **G9 — Audit.** Every sensitive or consequential automated action emits an audit event.
- **G10 — Language.** Outcome-oriented statuses only; never label a person "unfit" or
  "bad candidate". The product is not claimed to be automatically legally compliant.

---

# Part A — Recruitment

## 17. Resume–JD Matching & Candidate Shortlisting (UC-R01)

**Baseline:** Deterministic rules and scoring exist (Req 7, 8). This requirement extends the
criteria that a recruiter can express.

### Requirement 17.1 — Richer matching criteria
**User story:** As a Recruiter, I want matching to consider skills, experience, location and
(where enabled) compensation alignment, so that the shortlist reflects the JD.
#### Acceptance Criteria
1. The system SHALL support matching on skills, total and relevant experience, location /
   work mode, notice period and education using the existing typed rule nodes.
2. WHERE compensation fields are enabled for a campaign (Req 4.1.2) THE system SHALL be able
   to show expected-versus-budget alignment to authorised recruiters as **advisory
   information only**, and SHALL NOT use it as an automatic exclusion.
3. The system SHALL NOT use any attribute from the excluded list in Req 4.1.3 as a matching
   criterion.
4. WHEN a campaign uses a shortlist view THEN the system SHALL present matched candidates
   with the evidence for each criterion and SHALL route missing or low-confidence evidence to
   human review (G4).
5. WHEN the same inputs and rule version are evaluated THEN the system SHALL return the same
   shortlist order (determinism; see Req 8.1.4).

### Requirement 17.2 — Cross-campaign suggestions
#### Acceptance Criteria
1. The system MAY suggest "potential match for another campaign" using the existing
   outcome-oriented status, and SHALL require a recruiter to verify evidence before any
   contact (Req 11.3.2).

---

## 18. Resume Information Extraction (UC-R02)

**Baseline:** Basic extraction exists (Req 5.3).

### Requirement 18.1 — Structured candidate profile
#### Acceptance Criteria
1. The system SHALL maintain, per application, a structured record of name, contact details,
   skills (mapped to the taxonomy), employment history (employer, title, dates), total and
   relevant experience, education, certifications and location, each with source document,
   page, span, extraction method, confidence and verification status (Req 5.3.2).
2. The system SHALL show verified and unverified values separately (Req 5.3.4).
3. WHEN extraction confidence is below the configured threshold THEN the system SHALL flag
   the field for review rather than discarding or trusting it.
4. The system SHALL provide an export of the structured profile in CSV with formula-injection
   neutralisation (steering: `security.md`).

---

## 19. AI-Based Preliminary Screening (UC-R03)

**Baseline:** A voice interview agent exists in the `ai_interviews` module.

### Requirement 19.1 — Role-specific preliminary screening
**User story:** As a Recruiter, I want an initial role-specific screening conversation before
the technical round, so that interviewers spend time on better-prepared candidates.
#### Acceptance Criteria
1. WHEN a recruiter approves a preliminary screening for an application THEN the system SHALL
   generate role-specific questions from the approved JD for the recruiter to review and
   approve before any link is issued.
2. The system SHALL issue a single-use, expiring candidate link and SHALL record candidate
   consent before the session starts.
3. The system SHALL produce a transcript and a structured, evidence-linked summary of the
   candidate's **answers (content only)**.
4. The system SHALL NOT analyse voice, tone, face, emotion, or personality, and SHALL NOT
   produce any score derived from them (G7).
5. The output SHALL be advisory. The system SHALL NOT advance or reject an application
   because of it; a recruiter records the outcome (G1, G3).
6. IF the candidate cannot complete the session THEN the system SHALL offer an alternative
   (text or recruiter call) without penalty.
7. The system SHALL operate a deterministic fallback (scripted question set and manual
   recording) when the AI adapter is disabled (G2).

---

## 20. Interview Scheduling Automation (UC-R04) — Phase B

**Baseline:** Slots, capacity, invitations, panel assignment exist. Invitation approval is
mandatory (Req 10.1).

### Requirement 20.1 — Availability capture
#### Acceptance Criteria
1. The system SHALL allow interviewers to maintain availability windows and SHALL support
   reading free/busy from a connected calendar (Microsoft 365 / Outlook first; see Req 33.5
   for the integration pattern) behind a calendar-provider interface.
2. The system SHALL allow a candidate to choose from the proposed slots via the confirmation
   link in Req 22.

### Requirement 20.2 — Automated slot proposal
#### Acceptance Criteria
1. WHEN an interview invitation has been **approved** (Req 10.1) THEN the system SHALL
   propose slots that fit interviewer availability, panel composition, location / mode and
   slot capacity.
2. The system SHALL NOT propose or book interviews for applications whose invitation has
   not been approved, and SHALL NOT auto-invite on a score alone (Req 10.1.2).
3. IF no slot satisfies the constraints THEN the system SHALL notify the recruiter with the
   reason rather than overbooking.
4. WHEN a slot is confirmed THEN the system SHALL create a calendar event for the panel and
   SHALL update the slot capacity atomically (no double booking; Req 10.2.2).
5. WHEN an interviewer or candidate cancels THEN the system SHALL propose a replacement,
   keep the history, and notify affected parties (Req 21).

---

## 21. Candidate WhatsApp / Email Reminders and the Notification Platform (UC-R05) — Phase A

**Baseline:** Not implemented. This requirement implements and extends Req 12.1 and design
component "Notifications".

### Requirement 21.1 — Provider-neutral channels
#### Acceptance Criteria
1. The system SHALL send through channel adapters for **email** and **WhatsApp**, behind a
   provider-neutral interface, with MailHog in development.
2. The system SHALL report an explicit state per message: `queued`, `sent`, `delivered`,
   `failed`, `suppressed`, or `unconfigured`, and SHALL NOT report `sent` when no provider is
   configured.
3. WHERE a channel is unconfigured THE system SHALL show the recruiter a manual-send fallback
   (for example a prefilled message) and SHALL record that the send was manual.
4. For each message the system SHALL store the data listed in Req 12.1.2 plus the channel
   consent basis.

### Requirement 21.2 — Interview reminders and confirmations
#### Acceptance Criteria
1. WHEN an interview is scheduled THEN the system SHALL send a confirmation request and
   reminders at configurable offsets (for example T-24h and T-2h) on the candidate's
   preferred available channel.
2. WHEN the interview is cancelled or rescheduled THEN the system SHALL cancel pending
   reminders and send the update.
3. The system SHALL suppress reminders once the candidate has checked in or the application
   has left the interview states.
4. The system SHALL use versioned, HR-approved templates, support at least English, and keep
   the template language field extensible.

### Requirement 21.3 — Consent, preferences and safety
#### Acceptance Criteria
1. The system SHALL send WhatsApp messages only to candidates who have given channel consent,
   using provider-approved message templates, and SHALL honour opt-out immediately.
2. The system SHALL rate-limit outbound messages per recipient and per campaign, retry
   transient failures with back-off, and dead-letter permanent failures for HR visibility.
3. Candidate messages SHALL NOT contain internal scores or recruiter notes (G8).
4. The HR dashboard SHALL show notification failures (Req 15.1.1).

---

## 22. Candidate Confirmation and Interviewer Notification (UC-R06) — Phase A

### Requirement 22.1 — Confirmation capture
#### Acceptance Criteria
1. The system SHALL let a candidate confirm, decline, or request a reschedule through a
   signed, single-purpose, expiring link and, where the provider supports it, a reply on the
   same channel.
2. The link SHALL identify exactly one application and SHALL be unguessable, rate-limited,
   and not usable after expiry.
3. WHEN a candidate confirms THEN the system SHALL update the slot confirmation state and
   SHALL notify the assigned interviewer(s) automatically (acknowledgement).
4. WHEN a candidate declines or requests a reschedule THEN the system SHALL notify the
   recruiter and start the replacement flow in Req 20.2.5.
5. IF no response is received by the configured deadline THEN the system SHALL send a final
   reminder and then flag the item for the recruiter, without cancelling automatically.

---

## 23. Interview Feedback Summarisation (UC-R07) — Phase B

**Baseline:** Structured assessments exist (Req 10.3). No summarisation.

### Requirement 23.1 — Structured feedback record and summary
**User story:** As a Hiring Manager, I want interviewer feedback summarised into one
structured record, so that I can compare evidence quickly.
#### Acceptance Criteria
1. The system SHALL aggregate, per application, the criteria scores, free-text notes and
   recommendations that each interviewer submitted, preserving each interviewer's original
   entry unchanged.
2. The system SHALL produce a summary using **only text the interviewers entered**,
   listing areas of agreement, areas of disagreement, and evidence cited, with links back to
   the source entries.
3. The system SHALL NOT infer traits, sentiment about the person, or any characteristic not
   stated by an interviewer (G7).
4. The summary SHALL be labelled advisory and SHALL NOT change a recommendation or decision
   (G1).
5. WHERE the AI adapter is disabled THE system SHALL still produce a deterministic
   aggregation (tabulated scores and quoted notes) (G2).
6. The system SHALL record provider, model version and template version when AI is used
   (steering: `responsible-ai.md`).
7. Panel members SHALL see only summaries for candidates they interviewed; other access
   follows existing permissions (Req 1.2).

---

## 24. Recruitment SLA Monitoring and Follow-up (UC-R08) — Phase A

### Requirement 24.1 — SLA policy
**User story:** As HR, I want the 48-hour CV-shortlisting target monitored automatically, so
that delays are caught before they are missed.
#### Acceptance Criteria
1. The system SHALL support configurable SLA policies per campaign or template. The default
   policy SHALL be: **shortlisting decision within 48 hours** of the application becoming
   ready for review.
2. The system SHALL define the SLA clock start (application ready for review), pause
   conditions (for example awaiting candidate information) and stop (a recorded shortlist or
   review outcome), and SHALL support business-hours and holiday calendars.
3. WHEN an application is at risk (configurable threshold, default 75% of the window) THEN
   the system SHALL send a reminder to the responsible recruiter.
4. WHEN the window is breached THEN the system SHALL escalate along a configurable chain
   (recruiter → recruiter admin → HR owner) and record each escalation.
5. The system SHALL provide an SLA view with at-risk and breached counts per campaign and
   an aggregated trend, and SHALL NOT present league tables ranking individual recruiters
   (Req 15.1.2).
6. SLA timers SHALL be computed from stored timestamps so that results are reproducible and
   auditable (G9).
7. Extending the SLA for a specific application SHALL require a reason and be audited.

---

## 25. Naukri / NOCR and Other Sourcing Integration (UC-R09) — Phase 0 then E

### Requirement 25.1 — Feasibility first
#### Acceptance Criteria
1. The system SHALL deliver a **time-boxed feasibility assessment** for Naukri, NOCR and other
   sourcing platforms, covering available official APIs / partner programmes, commercial
   terms, data fields, rate limits, consent and lawful-basis implications, and effort.
2. The assessment SHALL conclude with a recommendation (proceed / defer / do not proceed) and
   an Architecture Decision Record.

### Requirement 25.2 — If approved: sourcing adapter
#### Acceptance Criteria
1. The system SHALL integrate only through **official, contractually permitted APIs or
   exports**, behind a `SourcingProvider` interface. Scraping and unauthorised automation
   are out of scope (product.md: social-media scraping is deferred).
2. WHEN candidates are imported THEN the system SHALL create applications attributed to the
   source, apply duplicate detection (Req 5.4), run the standard document pipeline, and
   record the lawful basis and notice provided.
3. Imported candidates SHALL NOT be added to the talent pool without the separate explicit
   consent in Req 11.3.1.
4. The system SHALL support source-effectiveness reporting in aggregate (Req 15.2.1).

---

## 26. Offer and Post-Selection Follow-ups (UC-R10) — Phase B

**Baseline:** Hiring decisions exist; no offer workflow.

### Requirement 26.1 — Offer tracking and reminders
#### Acceptance Criteria
1. WHEN a hiring decision of "select" is approved THEN the system SHALL create an **offer
   record** with states: drafted, approved, issued, accepted, declined, expired, withdrawn.
2. The system SHALL NOT issue an offer without an authorised approval, and SHALL NOT make or
   alter an offer automatically (G1).
3. WHILE an offer is issued and unanswered THE system SHALL send follow-up reminders on
   configurable schedules and SHALL notify the recruiter on expiry.
4. WHEN a candidate accepts THEN the system SHALL create the onboarding case in Req 27.1.
5. WHEN a candidate declines or an offer expires THEN the system SHALL notify the recruiter
   and offer a controlled path to the waitlist (Req 11.1).
6. Offer communications SHALL use versioned HR-approved templates and SHALL be logged
   (Req 21.1.4).

---

# Part B — Onboarding

## 27. Post-Selection Document Collection and Reminders (UC-R11, UC-O01, UC-O02) — Phase C

### Requirement 27.1 — Onboarding case and checklist
**User story:** As HR, I want the required joining documents requested automatically once a
candidate is selected, so that I do not chase documents by hand.
#### Acceptance Criteria
1. WHEN a candidate is marked selected (or accepts an offer, per campaign setting) THEN the
   system SHALL create an **onboarding case** and SHALL send the applicable document
   checklist (G6).
2. The system SHALL support document checklists by role, employment type and location, with
   per-item status: requested, submitted, in review, accepted, correction requested,
   waived.
3. The checklist content SHALL be maintained by HR in versioned templates.
4. The system SHALL NOT start onboarding data collection before selection or acceptance
   (G6), and SHALL keep onboarding data inaccessible to screening.

### Requirement 27.2 — Secure submission
#### Acceptance Criteria
1. A joiner SHALL submit documents through a signed, expiring link or authenticated portal
   using the existing validation, quarantine and malware-scan pipeline (G5).
2. Stored documents SHALL use encrypted object storage with signed short-lived access links
   only (open decision 8 in `docs/open-decisions.md` becomes mandatory for this feature).
3. Identity-number fields SHALL be masked by default and revealed only to authorised HR users
   with an audited reason (steering: `privacy.md`).
4. Document access SHALL be limited to authorised HR roles. System Administrators SHALL NOT
   receive automatic access to document content (Req 1.3.6).

### Requirement 27.3 — Reminders
#### Acceptance Criteria
1. WHILE required items are outstanding THE system SHALL send reminders by email and, with
   consent, WhatsApp, at configurable intervals up to a configurable maximum.
2. WHEN the maximum is reached or the joining date is near THEN the system SHALL escalate to
   the responsible HR user and show the case as at risk.
3. The system SHALL stop reminders as soon as all required items are accepted or waived.
4. Reminders SHALL list only the outstanding items and SHALL NOT include document contents.

---

## 28. AI-Assisted Document Verification (UC-R11, UC-O03) — Phase D

### Requirement 28.1 — Extraction and cross-check
**User story:** As HR, I want submitted documents checked against the candidate's recorded
information, so that gaps and inconsistencies are flagged early.
#### Acceptance Criteria
1. WHEN a document is accepted for review THEN the system SHALL extract the relevant fields
   (for example name, document number, issue and expiry dates, institution, qualification,
   employer, designation, dates of service) with confidence and source location.
2. The system SHALL compare extracted values with the verified application data and with
   other submitted documents and SHALL flag **missing**, **inconsistent**, **expired**,
   **unreadable**, or **low-confidence** items.
3. The system SHALL present flags to HR with the evidence side by side. A flag SHALL NOT
   reject the joiner, withdraw an offer, or change any status automatically (G1, G4).
4. HR SHALL be able to accept, request correction, waive or escalate each flag with a reason,
   and the action SHALL be audited (G3, G9).
5. The system SHALL treat document text as untrusted data (G5) and SHALL NOT follow
   instructions found in a document.
6. The system SHALL NOT claim authenticity verification or forgery detection. It performs
   consistency checks only, and integration with an authoritative source verifier is a
   separate decision.
7. WHERE the AI adapter is disabled THE system SHALL use deterministic OCR, pattern
   extraction and rule-based comparison, with lower coverage (G2).
8. Data sent to any external model SHALL be minimised and redacted of unnecessary personal
   data, and SHALL NOT include fields not needed for the check.

---

## 29. Pre-Joining Reminders (UC-O04) — Phase C

### Requirement 29.1 — Joining information
#### Acceptance Criteria
1. The system SHALL hold for each onboarding case the joining date, reporting manager,
   department, work location and role-level expectations (for example KPI summary), entered
   or confirmed by HR.
2. The system SHALL send pre-joining communications at configurable offsets before the joining
   date (for example T-7, T-2, T-1) containing reporting manager, department, joining
   logistics and approved role information.
3. HR SHALL approve the content of each template and each case's role/KPI text before it is
   first sent.
4. IF the joining date, manager or department changes THEN the system SHALL update the
   scheduled messages and send a correction where one has already gone out.
5. The system SHALL suppress messages once the joiner is marked withdrawn or no-show by HR.

---

## 30. AI Avatar-Based Induction (UC-O05) — Phase 0 then E

### Requirement 30.1 — Evaluation before build
#### Acceptance Criteria
1. The system SHALL first deliver a **time-boxed evaluation** of avatar / synthetic-video
   vendors covering cost, languages, content approval workflow, data residency, branding,
   accessibility (captions, transcripts) and risks, ending in an ADR.
2. If approved, avatar content SHALL be a **content-delivery** feature only. The system SHALL
   NOT analyse the employee's face, voice or reactions (G7).
3. Induction content (company introduction, policies, stakeholders, standard information)
   SHALL be authored and approved by HR before generation and SHALL be versioned.
4. The system SHALL disclose that the presenter is AI-generated, SHALL provide captions and a
   text transcript, and SHALL keep the existing recorded-video induction as a fallback.
5. The system SHALL record completion per employee and SHALL continue to issue the induction
   certificate on completion.
6. Using a real person's likeness or voice SHALL require that person's documented written
   consent.

---

## 31. Policy and Department SOP Distribution (UC-O06) — Phase C

### Requirement 31.1 — Controlled library
#### Acceptance Criteria
1. The system SHALL provide a versioned library of HR policies and department SOPs with
   owner, effective date, department / role / location audience and status
   (draft, approved, retired).
2. WHEN an onboarding case is created THEN the system SHALL assign the policies and SOPs that
   match the joiner's department, role and location and SHALL make them available from the
   joining date (or earlier where HR chooses).
3. The system SHALL record acknowledgement per joiner and per document version, and SHALL
   remind joiners about outstanding acknowledgements.
4. WHEN a policy is revised THEN the system SHALL keep prior versions, and SHALL NOT silently
   change what a joiner already acknowledged.
5. Only approved versions SHALL be distributed or used as a source for Req 32.

---

## 32. HR Text Assistant / Chatbot (UC-O07) — Phase D

**Baseline:** The existing assistant is rule-based and recruiter-facing only.

### Requirement 32.1 — Employee HR assistant
**User story:** As an Employee, I want to ask common HR questions in plain text, so that I
get quick answers about policies and holidays.
#### Acceptance Criteria
1. The system SHALL answer questions only from **approved** sources (Req 31, holiday
   calendar, HR-curated FAQ) and SHALL cite the source document and version for every
   answer.
2. IF no approved source answers the question THEN the system SHALL say so and offer to route
   the question to HR, and SHALL NOT guess.
3. The system SHALL NOT answer questions about another person's data, and SHALL NOT provide
   legal, medical or financial advice. Requests for personal HR data SHALL require
   authentication and SHALL return only the signed-in employee's own data, if enabled.
4. The system SHALL work with a deterministic retrieval / search mode when the AI adapter is
   disabled (G2); AI-assisted phrasing, when enabled, SHALL be constrained to retrieved
   text.
5. The system SHALL log questions and answers without personal identifiers beyond what is
   needed, apply retention rules, and give HR an aggregated "unanswered questions" report to
   improve content.
6. The system SHALL provide an accessible text interface (keyboard, screen-reader labels).

---

## 33. ZingHR Integration (UC-O08) — Phase 0 then E

### Requirement 33.1 — Feasibility first
#### Acceptance Criteria
1. The system SHALL deliver a **time-boxed assessment** of the ZingHR APIs (authentication,
   available endpoints for employee master, employee code creation, documents and other HR
   workflows, rate limits, sandbox availability, error model, licensing), ending in an ADR.
2. No API behaviour SHALL be assumed. The design SHALL be based on the vendor's documented,
   confirmed interfaces.

### Requirement 33.2 — Integration pattern (if approved)
#### Acceptance Criteria
1. The system SHALL integrate through an `HrmsProvider` interface so that the product does not
   depend on one vendor.
2. Before data is sent to ZingHR, an authorised HR user SHALL review and confirm it (no
   silent push of employee records).
3. Calls SHALL be idempotent, retried with back-off, and recorded; failures SHALL go to a
   work queue visible to HR with the reason.
4. The system SHALL map and send only the fields needed for the target workflow (data
   minimisation) and SHALL store the returned employee identifier against the onboarding
   case.
5. Credentials SHALL be held in a secret store and SHALL NOT appear in logs, audit events or
   configuration files in source control.
6. The integration SHALL be switchable off without affecting the core onboarding workflow.

---

## 34. Automated Welcome Communication (UC-O09) — Phase C

### Requirement 34.1 — Welcome and announcement
#### Acceptance Criteria
1. ON the joining date THE system SHALL send a welcome email to the new joiner, using an
   approved template.
2. ON the joining date THE system SHALL send an announcement email to the recipients HR has
   configured for that department / team.
3. HR SHALL approve the announcement text and the recipient list before it can be sent, and
   the announcement SHALL contain only information the joiner has agreed to share (for
   example name, role, team) — a photo or personal details SHALL require explicit consent.
4. IF the joining date changes or the joiner is withdrawn THEN the system SHALL cancel or
   reschedule the pending messages.
5. The system SHALL log both messages (Req 21.1.4).

---

# Part C — Cross-Cutting

## 35. Platform capabilities required by the long-term plan

### Requirement 35.1 — Scheduler and workflow engine
#### Acceptance Criteria
1. The system SHALL run time-based work (reminders, SLA checks, pre-joining and welcome
   messages) through scheduled background jobs (Dramatiq, ADR-0012), with idempotent
   execution, persisted schedules, and recovery after restart.
2. The system SHALL store UTC timestamps, apply the organisation's configured time zone for
   scheduling and display, and support a holiday calendar.

### Requirement 35.2 — Integration framework
#### Acceptance Criteria
1. The system SHALL provide an adapter pattern for calendar, messaging, sourcing, HRMS and
   AI providers, each with configuration validation at start-up, health reporting in
   `/ready`, and an explicit "not configured" state.
2. Provider secrets SHALL be held in an environment or secret store only.
3. Outbound calls SHALL use timeouts, retries with back-off and circuit-breaking, and SHALL
   send the minimum necessary data.

### Requirement 35.3 — New roles and permissions
#### Acceptance Criteria
1. The system SHALL add permissions for at least: `notification.template.manage`,
   `sla.policy.manage`, `onboarding.view`, `onboarding.manage`, `onboarding.document.view`,
   `onboarding.document.verify`, `policy.manage`, `integration.manage`, and
   `offer.manage`, assigned to roles per `docs/permission-matrix.md`, with object-level
   authorisation retained.
2. The joiner SHALL have a restricted identity limited to their own onboarding case and
   approved policy library.

### Requirement 35.4 — Privacy and retention extensions
#### Acceptance Criteria
1. The system SHALL add retention categories for onboarding documents, offer records,
   chat transcripts, notification logs and SLA records (Req 14.2).
2. The system SHALL support access, correction and deletion requests for onboarding data
   (Req 14.1) and SHALL record a legal-hold path.
3. The system SHALL update privacy notices to cover each new purpose before the feature is
   enabled, with versioning.

### Requirement 35.5 — Observability and reporting
#### Acceptance Criteria
1. The system SHALL expose metrics for message delivery, SLA outcomes, job failures and
   integration health, without candidate or employee PII in logs.
2. The HR dashboard SHALL add: SLA at-risk and breached, outstanding onboarding items,
   upcoming joiners, notification failures, unanswered assistant questions (aggregate).

---

# Long-Term Acceptance Criteria (gate for each phase)

- **LT-AC-01** Notifications are sent through a provider-neutral adapter and record
  `unconfigured` honestly when no provider exists. *(Phase A)*
- **LT-AC-02** Interview reminders are sent at configured offsets and stop when no longer
  relevant. *(A)*
- **LT-AC-03** A candidate's confirmation notifies the interviewer automatically. *(A)*
- **LT-AC-04** The 48-hour shortlisting SLA is tracked, with reminder and escalation, and no
  recruiter ranking is exposed. *(A)*
- **LT-AC-05** Interviews are proposed only for approved invitations and never double-book a
  slot. *(B)*
- **LT-AC-06** Interview feedback summaries cite interviewer entries, are advisory, and have a
  deterministic fallback. *(B)*
- **LT-AC-07** Offers cannot be issued without approval; offer follow-ups are tracked. *(B)*
- **LT-AC-08** Selecting a candidate creates an onboarding case and checklist; no onboarding
  data exists before selection. *(C)*
- **LT-AC-09** Document submission reminders stop when items are accepted or waived. *(C)*
- **LT-AC-10** Pre-joining and welcome messages are approved by HR, scheduled, and rescheduled
  on change. *(C)*
- **LT-AC-11** Policies and SOPs are versioned, targeted by department / role, and
  acknowledged per version. *(C)*
- **LT-AC-12** Document verification flags inconsistencies for HR and never changes a status
  automatically. *(D)*
- **LT-AC-13** The HR assistant answers only from approved sources with citations and escalates
  otherwise. *(D)*
- **LT-AC-14** Feasibility ADRs exist for sourcing platforms, ZingHR and avatar induction
  before any build starts. *(0)*
- **LT-AC-15** If ZingHR is approved, no employee record is pushed without HR confirmation,
  and the integration can be switched off. *(E)*
- **LT-AC-16** Every automated, consequential action produces an audit event, and the core
  workflow runs with all AI features disabled.

---

# Assumptions and Open Decisions (long-term)

### Assumptions
1. Email is delivered through a provider reachable by the organisation (Microsoft 365 /
   Outlook is assumed from stakeholder input); the adapter stays provider-neutral.
2. WhatsApp requires an approved business provider account and pre-approved message
   templates; candidates must opt in.
3. The 48-hour SLA applies to CV shortlisting and is measured from the application becoming
   ready for review. Business-hours treatment is configurable.
4. Single-organisation deployment continues (ADR-0016); the organisation key remains on all
   new tables.
5. All new capabilities ship **disabled by default** and are enabled per environment.

### Open decisions (not invented)
1. Which email and WhatsApp providers, and who owns the accounts and approvals.
2. Whether the SLA clock uses business hours and which holiday calendar.
3. Whether `salary` / `compensation` alignment may be shown in the shortlist (Req 17.1.2) and
   to whom.
4. Calendar provider and permission model for reading interviewer availability.
5. Which document types are in each checklist, and the handling policy for government
   identity numbers (masking, retention, legal review).
6. Whether document verification may use an external AI service for real personal documents
   (data-residency review) or must stay on deterministic / in-region processing.
7. Whether the HR assistant is limited to policies and holidays or may also return an
   employee's own leave / payslip data (requires HRMS integration).
8. Sourcing platform commercial terms and permitted data use.
9. ZingHR API availability, scope and sandbox access.
10. Avatar vendor, language coverage and whether real-person likeness is used.
11. Candidate self-service authentication (open decision 10 in `docs/open-decisions.md`) —
    needed for several of the flows above, or whether signed links suffice.

### Non-claims
The product is not claimed to be automatically legally compliant and is not claimed to be
risk-free. No vendor capability, API, price or legal conclusion is assumed in this document;
each is to be confirmed in the feasibility step named above.

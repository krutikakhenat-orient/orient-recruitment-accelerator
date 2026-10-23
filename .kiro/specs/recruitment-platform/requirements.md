# Requirements — Orient Recruitment Accelerator

## Introduction

Orient Recruitment Accelerator is a production-quality, secure, and explainable
recruitment campaign management and candidate screening platform. It lets an authorised
HR Head or recruiter create a separate recruitment project and campaign for every approved
hiring requirement, then run the full lifecycle from JD intake through candidate
application, deterministic and explainable screening, human review, interview workflow,
hiring decision, waitlist, consented talent pool, and governance (privacy, retention,
audit).

The screening core is **deterministic, version-controlled, and reproducible**. AI, if ever
enabled, may only extract, normalise, summarise, and recommend — never decide. The system
must run with AI disabled and must not depend on Kiro at runtime.

This document uses EARS-style acceptance criteria. Requirement IDs are stable references
used by `design.md` and `tasks.md`. Acceptance criteria AC-01..AC-25 at the end are the
MVP gate.

## Glossary

- **Project**: an approved hiring need; owns one or more campaigns.
- **Campaign**: one position-hiring effort within a project; owns versioned JD, rules,
  thresholds, and form.
- **JD Version / Rule-Set Version / Threshold Version / Form Version**: immutable once
  approved.
- **Candidate**: canonical individual profile. **Application**: a candidate's application
  to one campaign (answers snapshotted).
- **Screening Run**: an immutable record of one deterministic evaluation of an application.
- **Four-eyes**: a change requiring an approver different from the actor.

---

## 1. Identity, Access & Separation of Duties

### Requirement 1.1 — Authentication
**User story:** As a platform user, I want to authenticate securely, so that only
authorised people access the system.
#### Acceptance Criteria
1. WHEN a user submits valid local credentials THEN the system SHALL authenticate using
   Argon2id-verified passwords and issue a short-lived access token and a protected
   refresh token.
2. WHEN repeated failed logins occur for an account THEN the system SHALL apply account
   lockout and record a login-anomaly audit event.
3. The system SHALL expose an auth-provider interface that is ready for OIDC/SAML and TOTP
   MFA without changing calling code.
4. WHILE a session cookie is used THE system SHALL set it HttpOnly, Secure, and SameSite,
   and SHALL apply CSRF protection.

### Requirement 1.2 — Role-based + fine-grained permissions
**User story:** As a System Administrator, I want fine-grained permissions bundled into
roles, so that access follows least privilege.
#### Acceptance Criteria
1. The system SHALL implement fine-grained permissions including project.create,
   campaign.create/edit/approve/publish/pause, jd.upload/review/approve,
   rule.create/approve, threshold.change, candidate.view/export/correct,
   application.review, screening.execute/override, interview.approve/schedule,
   assessment.submit, hiring_decision.recommend/approve, waitlist.manage,
   talent_pool.search, audit.view, privacy_request.manage, user.manage, system.configure.
2. The system SHALL define roles HR Head, Recruitment Administrator, Recruiter, Hiring
   Manager, Interview Panel Member, Management Viewer, Compliance/Audit Viewer, System
   Administrator, and Candidate as permission bundles.
3. WHEN any permission is evaluated THEN the system SHALL additionally enforce object-level
   authorisation against the specific campaign/application the actor is assigned to.
4. IF a recruiter is assigned to one campaign THEN the system SHALL NOT grant that recruiter
   access to campaigns they are not assigned to.

### Requirement 1.3 — Separation of duties
**User story:** As HR governance, I want separation of duties enforced, so that no single
person can both create and solely approve consequential changes.
#### Acceptance Criteria
1. The system SHALL prevent the creator of an exclusion rule from being its sole approver.
2. WHEN four-eyes is configured for threshold changes THEN the system SHALL require an
   approver different from the actor.
3. The system SHALL prevent Interview Panel Members from altering screening rules.
4. The system SHALL prevent Candidates from viewing internal scores, reviewer comments, or
   other candidates' records.
5. The system SHALL restrict Compliance/Audit Viewers to read-only access.
6. The system SHALL NOT grant System Administrators automatic access to candidate content;
   any such access SHALL require explicit operational authorisation and SHALL be logged.

---

## 2. Projects & Campaigns

### Requirement 2.1 — Projects
**User story:** As a Recruiter/HR Head, I want to create projects, so that campaigns are
organised under an approved hiring need.
#### Acceptance Criteria
1. WHEN a user with project.create submits valid project data THEN the system SHALL create
   a project with id, name, business unit, department, business owner, HR owner,
   description, planned hiring period, status, and audit metadata.

### Requirement 2.2 — Campaigns
**User story:** As a Recruiter/HR Head, I want to create campaigns under a project, so
that each hiring requirement is managed separately.
#### Acceptance Criteria
1. WHEN a user with campaign.create submits valid campaign data THEN the system SHALL
   create a campaign with the specified fields (position title, type, openings, employment
   type, location, work mode, hiring manager, recruiter, opening/closing dates, status,
   approved JD/rule/form/threshold version references, retention policy, privacy-notice
   version, audit metadata).
2. The campaign SHALL reference its approved JD version, approved rule-set version,
   approved form version, and active threshold version.

### Requirement 2.3 — Campaign lifecycle state machine
**User story:** As HR governance, I want a controlled campaign lifecycle, so that invalid
transitions are impossible.
#### Acceptance Criteria
1. The system SHALL model campaign states: Draft, JD Uploaded, JD Review, Criteria
   Configuration, Criteria Review, Approval Pending, Approved, Published, Applications
   Open, Applications Closed, Screening, Human Review, Interview Planning, Interviewing,
   Selection Review, Completed, Closed, Archived, Paused, Cancelled.
2. WHEN a transition is requested THEN the system SHALL verify permitted source state,
   permitted destination state, required permission, required data, and required approval,
   and SHALL record transition reason, actor, timestamp, audit event, and candidate
   communication impact.
3. IF a transition is not defined in the transition table THEN the system SHALL reject it.
4. The system SHALL NOT allow campaign status changes through generic CRUD endpoints.

### Requirement 2.4 — Publication gating
**User story:** As HR governance, I want publication blocked until prerequisites exist, so
that no campaign goes live incomplete.
#### Acceptance Criteria
1. The system SHALL NOT allow campaign publication unless an approved JD version, approved
   rule-set version, approved form version, active threshold version, and a privacy-notice
   version are all present. (AC-04)

---

## 3. Job Descriptions

### Requirement 3.1 — Safe JD upload
**User story:** As a Recruiter, I want to upload a JD safely, so that malicious files
cannot harm the system.
#### Acceptance Criteria
1. The system SHALL accept PDF, DOCX, TXT, PNG, JPEG uploads.
2. WHEN a file is uploaded THEN the system SHALL validate extension, MIME type, and file
   signature, enforce size limits, calculate a file hash, detect duplicates, assign a safe
   generated filename, and quarantine the file before processing.
3. The system SHALL expose a malware-scanning adapter interface and scan quarantined files.
4. The system SHALL NOT execute or render untrusted content and SHALL NOT allow direct
   public object-storage access.

### Requirement 3.2 — JD extraction (suggestion only)
**User story:** As a Recruiter, I want proposed JD fields extracted, so that I can review
rather than retype.
#### Acceptance Criteria
1. WHEN a JD is processed THEN the system SHALL extract a structured draft (title,
   department, location, work mode, employment type, openings, responsibilities, min total
   experience, min relevant experience, optional max experience, mandatory skills,
   desirable skills, education, certifications, domain, shift, travel, notice period,
   joining expectations, compensation visibility, evidence required per criterion).
2. The system SHALL treat extraction as a suggestion and SHALL require HR or Hiring Manager
   review before approval.

### Requirement 3.3 — JD versioning & immutability
#### Acceptance Criteria
1. WHEN a JD version is approved THEN the system SHALL make it immutable. (AC-02)
2. IF a JD changes after applications have started THEN the system SHALL create a new JD
   version, create or link a new rule version, preserve the original screening result,
   require an explicit prospective-only or formal re-evaluation decision, and record the
   approver and reason.

---

## 4. Dynamic Application Form

### Requirement 4.1 — Campaign-specific form
**User story:** As a Recruitment Administrator, I want a campaign-specific form from an
approved schema, so that each campaign collects the right data.
#### Acceptance Criteria
1. The system SHALL generate a campaign form from an approved, versioned form schema with
   field classes: core identity/communication, campaign-specific eligibility, skills and
   experience, education/certification, availability, compensation (only if enabled),
   consent/declaration, resume/attachments.
2. Compensation fields SHALL default off and SHALL appear only when explicitly enabled and
   authorised for the campaign.
3. The system SHALL NOT include DOB, age, gender, marital status, medical condition,
   disability information, religion, caste, race/ethnicity, sexual orientation, photograph,
   vaccination status, hobbies, or family information in initial automated screening.
4. The system SHALL allow configurable accessibility-assistance fields that are never used
   as a screening criterion.

---

## 5. Candidate Application & Document Processing

### Requirement 5.1 — Public application
**User story:** As a Candidate, I want to apply through a campaign-specific public page, so
that I can submit my application.
#### Acceptance Criteria
1. WHEN a campaign is published and open THEN the system SHALL serve a public application
   link and accept applications through the campaign-specific form. (AC-05)
2. WHEN a candidate submits THEN the system SHALL require privacy consent and SHALL offer a
   separate optional talent-pool consent.
3. The system SHALL apply bot/rate-limiting controls to the public form.

### Requirement 5.2 — Candidate / Application separation
#### Acceptance Criteria
1. The system SHALL maintain a canonical Candidate record (contact, consent state, privacy
   requests, talent-pool status, duplicate/merge history) separate from Application records
   (per-campaign answers, documents, screening results, review, interview workflow,
   disposition).
2. WHEN the master candidate profile changes THEN the system SHALL NOT overwrite historical
   application answers.
3. A Candidate MAY apply to multiple campaigns.

### Requirement 5.3 — Resume processing pipeline
**User story:** As a Candidate, I want my resume processed safely and extracted accurately,
so that I can confirm the data.
#### Acceptance Criteria
1. WHEN a resume is uploaded THEN the system SHALL validate and quarantine it, scan via the
   malware adapter, determine file type from content, extract native text where possible,
   apply OCR fallback when required, strip active content/unsafe metadata, parse candidate
   fields, identify source pages/spans, assign extraction confidence, compare extracted vs
   candidate-entered fields, and flag contradictions. (AC-06)
2. For every extracted field the system SHALL store value, source document id, source page,
   source text span where feasible, extraction method, confidence, verification status,
   verified-by, and verified-timestamp.
3. The system SHALL NOT infer a qualification merely from semantically related text.
4. The system SHALL present extracted information to the candidate or HR for verification
   and SHALL store verified and unverified values separately. (AC-07)
5. The system SHALL defend against prompt injection, hidden text, keyword stuffing, zip
   bombs, path traversal, and malicious document metadata; document text SHALL NOT trigger
   tools, network calls, database commands, or code execution.

### Requirement 5.4 — Duplicate detection
#### Acceptance Criteria
1. WHEN an application matches an existing candidate (by contact/hash heuristics) THEN the
   system SHALL flag a potential duplicate for human review rather than auto-merging.

---

## 6. Skill Taxonomy

### Requirement 6.1 — Controlled taxonomy
#### Acceptance Criteria
1. The system SHALL maintain Skills (id, canonical name, category, description, active) and
   Skill Aliases (alias, canonical skill id, relationship type, approved-by, approved-date).
2. The system SHALL support exact aliases, abbreviations, previous product names, skill
   versions, and parent-child relationships.
3. The system SHALL NOT score "related but non-equivalent" skills as exact equivalents.

---

## 7. Rules Engine

### Requirement 7.1 — Deterministic typed-JSON rules
**User story:** As a Recruiter, I want to configure screening rules as typed data, so that
evaluation is deterministic and safe.
#### Acceptance Criteria
1. The system SHALL evaluate rules using a restricted, typed JSON DSL and SHALL NOT evaluate
   arbitrary Python, JavaScript, or SQL stored in rules.
2. The system SHALL support rule node types: boolean, numeric_comparison, numeric_range,
   text_enum, exact_skill, skill_experience, verified_certification, education, location,
   notice_period, relevant_experience, evidence_present, confidence_threshold, and logical
   groups and/or/not.
3. Each rule SHALL include rule id, version, campaign/template association, name,
   description, criterion type, operator, expected value, weight, mandatory flag,
   missing-evidence behaviour, manual-review behaviour, active date, expiry date, creator,
   approver, approval status, and change reason.
4. WHEN a rule contains an unsupported operator or is malformed THEN the system SHALL reject
   it at validation time, before approval.

### Requirement 7.2 — Rule & threshold approval and versioning
#### Acceptance Criteria
1. WHEN a rule set is approved THEN the system SHALL version it and make the approved
   version immutable. (AC-03)
2. WHEN a threshold is changed THEN the system SHALL require threshold.change permission and
   a reason, SHALL create a new threshold version, and SHALL emit an audit event. (AC-12)
3. IF an unauthorised user attempts a threshold change THEN the system SHALL deny it. (AC-11)

---

## 8. Screening

### Requirement 8.1 — Deterministic, reproducible screening
**User story:** As a Recruiter, I want screening to use only the approved rule version, so
that results are reproducible and governed.
#### Acceptance Criteria
1. WHEN screening executes THEN the system SHALL use only the approved rule-set version,
   active threshold version, approved JD version, approved form version, and the current
   extraction version. (AC-08)
2. The system SHALL structure screening as validation, eligibility gates, weighted fit
   score, confidence assessment, human-review triggers, and final recommendation status.
3. WHEN screening completes THEN the system SHALL store an immutable Screening Run with:
   run id, application id, JD version, rule-set version, threshold version, form version,
   extraction version, started/completed timestamps, score, eligibility outcome, confidence
   status, criterion-by-criterion results, evidence references, missing evidence, conflicts,
   recommendation, manual-review requirement, processing errors, input-data hash, and engine
   version.
4. WHEN the same inputs and rule version are evaluated again THEN the system SHALL produce
   identical results. (AC regression)
5. The system SHALL produce only outcome-oriented statuses (e.g. Ready for HR Review,
   Mandatory Criterion Confirmed/Not Confirmed, Additional Information Required, Data
   Conflict, Low Extraction Confidence, Recommended for Interview Review, Borderline Review,
   Waitlist Review, Potential Match for Another Campaign) and SHALL NOT use labels such as
   "bad candidate" or "unfit person".

### Requirement 8.2 — No sole-AI / no auto-rejection
#### Acceptance Criteria
1. The system SHALL NOT reject a candidate solely because a score is below a threshold.
2. The system SHALL NOT base any rejection solely on an LLM output.
3. WHEN evidence is missing or confidence is low or data conflicts THEN the system SHALL
   route the application to human review rather than disqualifying it. (AC-10)

### Requirement 8.3 — Explainable score
#### Acceptance Criteria
1. For every scored criterion the system SHALL display criterion name, mandatory/desirable,
   expected requirement, candidate evidence, evidence source, confidence, maximum score,
   awarded score, reason, reviewer modification, override reason, and approver. (AC-09)
2. The score SHALL be reproducible from stored inputs and the stored rule version.

---

## 9. Human Review

### Requirement 9.1 — Review queue & actions
#### Acceptance Criteria
1. The system SHALL populate a review queue with unverified extracted values, missing
   mandatory evidence, conflicting values, low-confidence extraction, borderline scores,
   duplicate candidates, requested exceptions, and potential alternative-role matches.
2. The system SHALL support reviewer actions: confirm evidence, correct extracted value,
   request candidate clarification, recommend interview, recommend waitlist, recommend
   alternative campaign, escalate to hiring manager, submit exception request.
3. WHEN a reviewer corrects a value THEN the system SHALL NOT silently alter the original
   extracted record and SHALL store the original value, corrected value, correction reason,
   actor, and timestamp.

---

## 10. Interviews, Slots & Assessment

### Requirement 10.1 — Interview approval & invitation
#### Acceptance Criteria
1. WHEN an interview invitation is issued THEN the system SHALL require the configured
   authorised approval (interview.approve). (AC-14)
2. The system SHALL NOT auto-invite a candidate merely because a numeric threshold was
   crossed, unless the campaign is explicitly configured for auto-invitation under approved
   governance; the default SHALL be human approval.

### Requirement 10.2 — Slots & attendance
#### Acceptance Criteria
1. The system SHALL support interview stages, walk-in dates, slots with capacity, location,
   mode, panel assignment, invitation status, candidate confirmation, attendance, no-show,
   and reschedule.
2. WHEN slot capacity is reached THEN the system SHALL prevent further confirmations for
   that slot.

### Requirement 10.3 — Structured assessment (separate from pre-screening)
#### Acceptance Criteria
1. The system SHALL keep interviewer assessment separate from pre-screening and SHALL
   support role-specific technical criteria, communication criteria, problem-solving
   evidence, role understanding, interview notes, recommendation, and conflict declaration.
2. The system SHALL NOT provide personality, emotion, facial-expression, voice-stress, or
   medical inference features, and SHALL NOT infer characteristics from video, voice, or
   appearance.

### Requirement 10.4 — Hiring decisions
#### Acceptance Criteria
1. The system SHALL support selection, rejection, hold, and withdrawal workflows with
   recommend and approve steps, each audited.

---

## 11. Waitlist, Re-evaluation & Talent Pool

### Requirement 11.1 — Waitlist
#### Acceptance Criteria
1. A waitlist record SHALL include application, campaign, reason, current screening version,
   eligibility state, expiry, and candidate communication status.

### Requirement 11.2 — Controlled re-evaluation
#### Acceptance Criteria
1. The system SHALL allow re-evaluation only when the JD version, rule version, or threshold
   version changes, OR the candidate provides new verified information, OR an authorised
   reviewer requests reprocessing.
2. WHEN re-evaluation occurs THEN the system SHALL preserve the original result, create a new
   screening run, record the initiating user and reason, identify changed rules, show old
   versus new result, and require approval before new candidate communication. (AC-13)

### Requirement 11.3 — Talent pool (separate consent)
#### Acceptance Criteria
1. Talent-pool inclusion SHALL require separate explicit consent and SHALL store consent
   version, date, expiry, permitted purposes, withdrawal date, and retention status.
2. WHEN a future campaign identifies a possible historical match THEN the system SHALL
   require a recruiter to verify evidence before contacting the candidate.
3. The system SHALL provide consent-withdrawal and deletion workflows. (AC-16)

---

## 12. Notifications

### Requirement 12.1 — Provider-neutral notifications
#### Acceptance Criteria
1. The system SHALL support application acknowledgement, missing-information request,
   interview invitation, slot confirmation, reminder, reschedule, waitlist notice, campaign
   closure, candidate withdrawal acknowledgement, talent-pool consent status, and
   privacy-request acknowledgement.
2. For each notification the system SHALL store template version, recipient, communication
   purpose, delivery channel, delivery status, provider response id, failure reason, and
   timestamp.
3. The system SHALL NOT include internal scores or sensitive recruiter notes in candidate
   communications by default. (AC-15)

---

## 13. Audit

### Requirement 13.1 — Append-only audit trail
#### Acceptance Criteria
1. The system SHALL record append-only audit events for at least: authentication events,
   permission changes, campaign creation/edits, JD uploads/approvals, rule creation/approval,
   threshold changes, campaign publication, candidate profile access, sensitive data exports,
   screening runs, manual corrections, overrides, candidate status changes, interview
   approvals, final decisions, waitlist changes, talent-pool access, privacy requests,
   retention/deletion actions, and administrative configuration. (AC-23)
2. Each audit event SHALL include event id, tenant id, actor id, actor role, action, entity
   type, entity id, previous-state reference, new-state reference, reason, timestamp,
   correlation id, request id, security context where appropriate, and an integrity-hash /
   tamper-evidence strategy.
3. The system SHALL NOT store passwords, access tokens, resume content, or unnecessary PII
   in audit logs.

---

## 14. Privacy & Retention

### Requirement 14.1 — Privacy requests & rights
#### Acceptance Criteria
1. The system SHALL support purpose-specific consent, privacy-notice versioning, data
   minimisation, candidate correction, consent withdrawal, talent-pool opt-in, access/export
   request workflow, processing restriction, and communication preferences.

### Requirement 14.2 — Retention
#### Acceptance Criteria
1. The system SHALL implement configurable retention policies per record category (candidate
   identity, campaign application, resume, screening result, interview assessment, candidate
   communication, talent-pool record, audit evidence, security logs). (AC-17)
2. Retention actions SHALL include notify owner, restrict access, delete, anonymise, and
   extend under approved legal hold, and every retention action SHALL be logged.

---

## 15. Dashboards & Reporting

### Requirement 15.1 — HR dashboard
#### Acceptance Criteria
1. The system SHALL display active campaigns, applications by campaign, screening status,
   human-review backlog, interview invitations, confirmed candidates, attendance, selection
   funnel, campaign vacancies, waitlist, talent-pool candidates, notification failures,
   pending approvals, data-quality exceptions, and privacy/retention actions.
2. The system SHALL NOT display misleading performance rankings of individual recruiters or
   interviewers.

### Requirement 15.2 — Management dashboard
#### Acceptance Criteria
1. The system SHALL display aggregated indicators (open campaigns, positions, applications,
   screening queue, interview funnel, selected candidates, joined candidates where available,
   source effectiveness, campaign ageing, vacancies remaining, approval backlog).
2. The system SHALL suppress small-group or sensitive breakdowns where disclosure could
   expose individual candidate information.

---

## 16. Platform-wide Non-functional, Security, AI-safety

### Requirement 16.1 — Security by default
See steering/security.md. The system SHALL enforce object-level authorisation server-side
regardless of UI; defend against SQLi, XSS, CSRF, SSRF, broken access control, IDOR, mass
assignment, path traversal, malicious upload, zip bombs, CSV formula injection, credential
stuffing, enumeration, bot submissions, prompt injection, hidden text/keyword stuffing,
malicious metadata, and excessive export. Malicious/unsupported uploads SHALL be blocked or
quarantined. (AC-18, AC-19)

### Requirement 16.2 — Operability without AI
#### Acceptance Criteria
1. WHEN optional AI services are disabled THEN the system SHALL complete the core workflow
   using the deterministic pipeline. (AC-22)
2. The core workflow SHALL NOT depend on Kiro at runtime.

### Requirement 16.3 — Deploy, backup, restore
#### Acceptance Criteria
1. The system SHALL provide deployment instructions that initialise the application from a
   clean environment. (AC-24)
2. The system SHALL provide documented, testable backup and restore procedures. (AC-25)

### Requirement 16.4 — Synthetic-only test data
#### Acceptance Criteria
1. Seed and test data SHALL contain no real candidate information and SHALL clearly mark all
   synthetic candidates and resumes as synthetic. (AC-21)

---

## MVP Acceptance Criteria (gate)

- AC-01 HR can create a project and campaign.
- AC-02 HR can upload and approve a versioned JD (immutable once approved).
- AC-03 HR can configure and approve versioned screening rules.
- AC-04 Campaign cannot be published without approved JD, rules, privacy notice, form, and
  active threshold.
- AC-05 A candidate can apply through a campaign-specific page.
- AC-06 A candidate can upload a supported resume safely.
- AC-07 Extracted data can be reviewed and corrected; verified/unverified stored separately.
- AC-08 Screening uses only the approved rule version.
- AC-09 Every score component shows evidence and rationale.
- AC-10 Low-confidence information enters manual review.
- AC-11 An unauthorised user cannot change a threshold.
- AC-12 A threshold change creates a new version and audit event.
- AC-13 Re-evaluation preserves the original screening result.
- AC-14 Interview invitation requires the configured approval.
- AC-15 Candidate communications do not expose internal scores.
- AC-16 The candidate can withdraw talent-pool consent.
- AC-17 Data retention actions are configurable and auditable.
- AC-18 Cross-role and object-level access tests pass.
- AC-19 Malicious and unsupported uploads are blocked or quarantined.
- AC-20 Critical API, domain, and end-to-end tests pass.
- AC-21 No real candidate information exists in seed or test data.
- AC-22 The system can operate when optional AI services are disabled.
- AC-23 All critical actions generate audit events.
- AC-24 Deployment instructions can initialise the application from a clean environment.
- AC-25 Backup and restore procedures are documented and testable.

---

## Assumptions & Open Decisions

### Assumptions (safest reasonable defaults chosen)
1. Single-organisation deployment for MVP; an org/tenant key is carried in the data model so
   multi-tenant SaaS can be added later (ADR-0016). Full multi-tenant isolation is deferred.
2. Background jobs use Dramatiq over Celery (ADR-0012).
3. Local identity = username/password (Argon2id) + TOTP MFA scaffold; OIDC/SAML behind an
   interface, not implemented in MVP.
4. Baseline extraction is non-LLM (PyMuPDF/pdfminer, python-docx, Tesseract OCR), pattern-
   based with explicit confidence; no semantic qualification inference.
5. Malware scanning is an adapter with a ClamAV-compatible dev implementation; a no-op
   scanner is explicitly flagged non-production.
6. Compensation fields default off/hidden unless explicitly enabled and authorised.
7. Email uses MailHog dev sandbox; provider adapter is neutral.
8. Retention/anonymisation jobs act destructively only after an owner-notification window.

### Open Decisions (flagged, not invented)
1. Field-level encryption mechanism for sensitive PII (app-layer envelope vs pgcrypto vs
   KMS) — readiness only in MVP.
2. Audit tamper-evidence strategy — default per-event hash + prev-hash chain; WORM storage
   to be revisited.
3. Re-evaluation approval granularity (per-run vs per-campaign-batch) — default per-run.
4. First enterprise SSO protocol (OIDC vs SAML) — interface-ready, undecided.
5. Production OCR engine licensing posture — Tesseract assumed, flagged.

### Non-claims
The product is not claimed to be automatically legally compliant and is not claimed to be
risk-free. No external product capabilities, legal conclusions, credentials, URLs, APIs, or
business rules are invented. No sample candidates are presented as real people.

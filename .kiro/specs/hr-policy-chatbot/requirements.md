# Requirements: HR Policy Chatbot (Bedrock Knowledge Base + S3 Vectors)

**Status:** Draft v0.1 | **Date:** 2026-11-13 | **Owner:** Product / HR Technology
**Companion documents:** [design.md](design.md), [tasks.md](tasks.md).
Extends the existing `policies` module and the keyword `/assistant/ask` described in
`docs/USER_GUIDE.md`. Does not change the MVP in `../recruitment-platform/requirements.md`.

## Introduction

HR staff upload HR policy documents. The documents are stored in Amazon S3, indexed by an
Amazon Bedrock Knowledge Base that uses Amazon S3 Vectors as its vector store, and a simple
chatbot answers employee questions only from that approved content, with citations. If the
Knowledge Base is off or unavailable, the existing keyword assistant keeps working.

## Glossary

- **Policy Document**: an HR policy, SOP or FAQ held in `policy_document`, versioned.
- **Docs Bucket**: private S3 bucket holding uploaded files under `quarantine/`, `draft/`, `approved/`.
- **Knowledge Base (KB)**: the Bedrock Knowledge Base whose only data source is `approved/` in the Docs Bucket.
- **Vector Store**: an S3 Vectors bucket and index used by the KB.
- **Sync**: a Bedrock ingestion job that updates the KB from the data source.
- **Chatbot**: the employee-facing question and answer feature.
- **HR Policy Manager**: a user holding the existing policy permission (`campaign.approve`).
- **Employee**: a signed-in user asking a question.

## Requirements

### Requirement 1: HR uploads policy documents

**User story:** As an HR Policy Manager, I want to upload policy files, so that the chatbot can answer from them.

1. THE system SHALL accept PDF, DOCX, TXT and MD files up to a configured size limit.
2. WHEN a file is uploaded, THE system SHALL validate extension, MIME type and file signature, compute a content hash, and run the malware-scan adapter before the file leaves `quarantine/`.
3. IF validation or scanning fails, THEN THE system SHALL reject the file, keep it out of `draft/` and `approved/`, and show a plain-language reason.
4. WHEN a file passes, THE system SHALL create a draft Policy Document with title, kind, audience, effective date and review-due date, and store the file in `draft/`.
5. IF the same content hash already exists for the organisation, THEN THE system SHALL warn the user before creating a duplicate.
6. THE system SHALL also allow a policy or FAQ to be typed in; it SHALL be stored as a Markdown object so it follows the same path.

### Requirement 2: Approval controls what is searchable

**User story:** As HR leadership, I want only approved content searchable, so that employees never see drafts.

1. THE Knowledge Base data source SHALL include only the `approved/` prefix.
2. WHEN an HR Policy Manager uploads or saves a Policy Document, THE system SHALL publish it in the same step (unless "Save as draft" is chosen), copy the file to `approved/` with a metadata sidecar (policy id, version, title, audience, effective date) and start a Sync. A draft is published later with one Publish action. (Changed 2026-11-14 at the product owner's request: one step instead of upload-then-approve.)
2a. THE system SHALL show HR, for every published policy, whether it is synced to the chatbot (Synced / Syncing / Sync failed with the reason / Not synced), a summary of how many are synced, and a confirmation when a sync finishes.
2b. THE system SHALL refuse to publish an FAQ draft whose answer is still the placeholder.
3. THE system SHALL apply existing separation-of-duties rules to approval and SHALL write an audit event.
4. WHEN a policy is revised, THE system SHALL create a new version, keep the old version searchable until the new version is Ready, then remove the old object and Sync.
5. WHEN a policy is retired, THE system SHALL remove its object from `approved/` and Sync, and the policy SHALL stop appearing in answers.
6. THE system SHALL NOT edit an approved version in place.

### Requirement 3: Index status is visible and recoverable

**User story:** As an HR Policy Manager, I want to see whether a document is searchable, so that I know when the chatbot can use it.

1. THE system SHALL show each approved policy as Indexing, Ready or Index failed, using text as well as colour or icon.
2. THE system SHALL poll Sync status in the background and record the job id, time and any failure reason.
3. IF a Sync fails, THEN THE system SHALL keep the previous Ready version in use and offer a Reindex action to HR.
4. WHILE a Sync is running, THE system SHALL queue further changes and merge them into the next Sync.
5. A scheduled reconcile job SHALL compare `approved/` objects with approved policies and correct any difference, logging each correction.
6. IF a file has no readable text (for example a scanned image), THEN THE system SHALL say the text could not be read and ask for a text version.

### Requirement 4: Employees ask questions and get cited answers

**User story:** As an Employee, I want a quick answer to an HR question, so that I do not need to read the whole policy.

1. THE Chatbot SHALL be available to signed-in employees on a page and through the existing assistant panel.
2. WHEN a question is submitted, THE system SHALL retrieve passages from the KB using a metadata filter for the asker's audience plus "everyone".
3. IF no retrieved passage meets the configured relevance threshold, THEN THE system SHALL reply that it could not find the answer in approved HR policies and offer "Send to HR".
4. THE system SHALL generate the answer only from retrieved passages and SHALL show source title, version and page for each citation.
5. IF a generated answer has no citation from the retrieved set, THEN THE system SHALL discard it and use the "not found" reply.
6. THE system SHALL NOT answer questions about an individual's own data (for example leave balance) and SHALL point to where that information is held.
7. THE Chatbot SHALL show a notice that answers come from approved company policy and that HR decides individual cases.
8. THE system SHALL keep recent conversation turns in the browser only and SHALL NOT store them on the server.

### Requirement 5: Safe handling of untrusted documents and questions

1. THE system SHALL treat document text as data; instructions inside a document SHALL NOT change system behaviour, call tools, or trigger network, database or code actions.
2. THE generation step SHALL have no tools and SHALL receive passages as quoted context.
3. THE system SHALL apply a Bedrock Guardrail to questions and answers for personal data, abusive content and HR-configured sensitive topics.
4. THE system SHALL rate-limit the ask endpoint per user and per client address.
5. THE system SHALL render answers and quoted text as plain text, never as HTML.
6. THE system SHALL NOT index candidate or employee personal data.

### Requirement 6: Fallback without Bedrock

1. THE system SHALL provide a setting that selects `bedrock_kb` or `keyword` as the answer backend, defaulting to `keyword` in local runs.
2. IF Bedrock or the KB is unavailable or not configured, THEN THE system SHALL fall back to the keyword assistant and show a banner saying smart search is unavailable.
3. THE system SHALL NOT claim a Bedrock answer when the keyword backend produced it, and SHALL log which backend answered.
4. THE feature SHALL be disabled by default and SHALL be switchable off without a deployment.
5. THE core recruitment workflow SHALL NOT depend on this feature.

### Requirement 7: Feedback and escalation to HR

1. WHEN an answer is shown, THE system SHALL let the employee mark it helpful or not helpful, with an optional comment of at most 300 characters.
2. WHEN the employee chooses "Send to HR", THE system SHALL create an HR question with the question text and an optional contact preference.
3. HR SHALL see an inbox of open questions, answer them, and close them.
4. WHEN HR reviews an unanswered question, THE system SHALL let HR create an FAQ draft from it.
5. Sensitive creation endpoints SHALL accept an idempotency key.

### Requirement 8: Privacy-preserving logs and insights

1. THE query log SHALL store no user identifier, and SHALL store the question after the PII guardrail check.
2. THE query log SHALL record whether an answer was found, the backend used, top relevance score and latency.
3. HR insights SHALL show aggregated top questions, unanswered questions, not-helpful rate and policies past their review date, with no per-person view.
4. THE system SHALL write audit events for upload, approve, revise, retire, reindex, sync result and HR answers.
5. Logs SHALL be structured, carry a correlation id, and contain no personal data.

### Requirement 9: Infrastructure and security

1. THE Docs Bucket SHALL be private, encrypted with a customer-managed key, versioned, with public access blocked.
2. THE Vector Store index SHALL use cosine distance and a dimension that matches the chosen embedding model.
3. IAM roles for the KB and the backend SHALL be limited to the specific bucket, index, KB and model ARNs.
4. HR "open original" SHALL use short-lived signed links only.
5. Infrastructure SHALL be defined in `Orient_Internal_AI_Deployment/terraform/` and released through the existing UAT then production path, with the account's standard tags.
6. Region availability, model access and Terraform provider support SHALL be verified by a spike before build (see design.md, Open Items).

### Requirement 10: Accessibility and usability

1. THE Chatbot and HR screens SHALL be keyboard operable with visible focus and labelled controls.
2. New answers SHALL be announced through an `aria-live` region and focus SHALL return to the input.
3. Status SHALL never rely on colour alone.
4. THE UI SHALL show clear loading, empty and error states and SHALL NOT show a blank page while the database or Bedrock wakes up.

## Acceptance gate (CB-AC)

- CB-AC-01: A synthetic PDF uploaded, approved and Ready is answered with a correct citation.
- CB-AC-02: A draft or retired policy is never returned in an answer.
- CB-AC-03: A question with no relevant passage returns the "not found" reply and can be sent to HR.
- CB-AC-04: An employee in one audience cannot receive another audience's content.
- CB-AC-05: A document containing injection text does not change behaviour.
- CB-AC-06: With Bedrock disabled, the keyword fallback answers and the banner is shown.
- CB-AC-07: Query logs contain no user identifier.
- CB-AC-08: Axe checks pass on the chatbot and HR upload screens.

## Out of scope

Decisions on leave, grievance or pay cases; answers about one person's own data until an HRMS integration exists; voice or emotion features; training on chat logs; multi-language support (parked, see Open Questions).

## Open questions

1. Who can ask: employees only, or also candidates and new joiners?
2. Do policies differ by department, location or grade?
3. Must policy text stay in India (affects generation model and inference profile)?
4. Preferred generation model (Claude or Nova) given what is enabled in Orient_Internal_AI.
5. Should "Send to HR" send an email, or stay in the in-app inbox?
6. English only, or Hindi too?

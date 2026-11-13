# Implementation Plan: HR Policy Chatbot

Test-first where practical. Each task lists the requirements it satisfies.
Feature ships disabled by default (`ORA_HR_CHATBOT_ENABLED=false`).

Status (2026-11-13, branch `feat/hr-policy-chatbot`): Phases 2-6 built and tested locally with
the keyword backend and a botocore-stubbed / fake Bedrock KB. Nothing is provisioned in AWS.
Phase 0 (spike), the Terraform tasks and the UAT rollout remain.

## Phase 0: Spike and decisions

- [x] 0.1 Manually create in Orient_Internal_AI (ap-south-1): Docs Bucket, S3 Vectors bucket and index, Knowledge Base, data source on `approved/`. Ingest 3 synthetic policies and test `Retrieve` and `Converse`. _Req 9.6_
  - Done 2026-11-13 and torn down; see `docs/hr-chatbot-phase0-findings.md`. Fixed 2 bugs found (empty sidecar attribute; guardrail on quoted passages) and raised the score threshold to 0.65.
- [x] 0.2 Check Terraform provider support for the KB with S3 Vectors; decide Terraform versus script. _Req 9.5_
  - AWS provider 6.72.0 supports every resource: Terraform.
- [x] 0.3 Write ADR `docs/adr/ADR-0017-hr-policy-chatbot-bedrock-kb.md`. _Req 9, 6_
- [ ] 0.4 Resolve open questions in requirements.md (audience, residency, model, email, language).
  - Partly answered by the trial: an India-only Claude Haiku 4.5 profile exists, so residency can be met. Still a business decision.
  - Interim choices in code: audience = `everyone` + `role:<role>` tags (department/location tags accepted but no user profile field yet); "Send to HR" is in-app only; English only.

## Phase 1: Infrastructure

- [ ] 1.1 Terraform: Docs Bucket (KMS, versioning, lifecycle), S3 Vectors bucket and index, KB, data source, Guardrail. _Req 9.1, 9.2_
- [ ] 1.2 Terraform: IAM roles for KB and backend, scoped to ARNs; standard tags. _Req 9.3, 9.5_
  - Also: EventBridge schedules for the ops Lambda actions `kb_index_poll` (every few minutes) and `kb_reconcile` (nightly).
- [x] 1.3 Add env config and startup validation for the new `ORA_*` settings. _Req 6.1, 6.4_
- [ ] 1.4 Release through UAT (develop) first; document in `docs/deployment.md`. _Req 9.5_

## Phase 2: Data model and adapter

- [x] 2.1 Alembic migration `0014_hr_policy_chatbot`: new columns on `policy_document`; tables `kb_sync_request`, `assistant_feedback`, `hr_question`; extra columns on `assistant_query_log`. Migration test. _Req 3, 7, 8_
- [x] 2.2 Define `KnowledgeBase` protocol and shared contract test suite. _Req 6_
- [x] 2.3 Implement `KeywordKnowledgeBase` by moving the existing matcher behind the interface; existing assistant tests must still pass. _Req 6.2_
- [x] 2.4 Implement `BedrockKnowledgeBase` (boto3: S3, bedrock-agent, bedrock-agent-runtime) with botocore stubber tests. _Req 2, 3, 4_
- [x] 2.5 Implement sync coalescing using `kb_sync_request`. _Req 3.4_

## Phase 3: HR upload and indexing

- [x] 3.1 Upload endpoint: extension, MIME, signature, size, hash, duplicate warning, malware-scan adapter, quarantine. Security tests (fake extension, zip bomb, path traversal, bad metadata). _Req 1.1-1.5_
- [x] 3.2 Draft creation, typed-in policy and FAQ stored as Markdown objects. _Req 1.4, 1.6_
- [x] 3.3 Approve flow: copy to `approved/` with metadata sidecar, start sync, audit event, separation of duties. _Req 2.1-2.3_
  - Note: approval keeps the existing rule (campaign.approve); no new four-eyes rule was added for policies.
- [x] 3.4 Revise and retire flows with delayed removal of the old version. _Req 2.4-2.6_
- [x] 3.5 `index_poller` (ops action `kb_index_poll`, plus on-demand poll in `index-status`) and `index-status` and `reindex` endpoints. _Req 3.1-3.3, 3.6_
- [x] 3.6 `kb_reconcile` nightly job (ops action `kb_reconcile`) with logging of corrections. _Req 3.5_
- [x] 3.7 Signed short-lived link for "open original" (S3 store), attachment download otherwise. _Req 9.4_

## Phase 4: Chatbot answers

- [x] 4.1 Audience filter builder and tests (IDOR-style: one audience cannot read another's). _Req 4.2_
- [x] 4.2 `AnswerComposer` with Bedrock `Converse`, fixed prompt, no tools; quoting composer for keyword backend. _Req 4.4, 5.1, 5.2_
- [x] 4.3 `assistant/ask`: guardrail, rate limit, retrieve, threshold, citation check, not-found path, logging without user id. Tests for each rule. _Req 4.3-4.6, 5.3, 5.4, 8.1, 8.2_
  - Rate limit is per process (see `assistant/ratelimit.py`); a shared limiter is a follow-up.
- [x] 4.4 Fallback to keyword on Bedrock failure with `answered_via`. _Req 6.2, 6.3_
- [x] 4.5 Injection test corpus (synthetic documents with hostile text). _Req 5.1, CB-AC-05_
  - Covered against the keyword path and the prompt builder; re-run against a live model in UAT.
- [x] 4.6 Self-service guard: reply with signpost for personal-data questions. _Req 4.6_

## Phase 5: Feedback, escalation and insights

- [x] 5.1 Feedback endpoint (comment limit 300). _Req 7.1_
- [x] 5.2 Escalate endpoint with idempotency key; HR inbox, answer and close endpoints. _Req 7.2, 7.3, 7.5_
- [x] 5.3 Create FAQ draft from an unanswered question. _Req 7.4_
- [x] 5.4 Insights endpoint (aggregates only, review-due list). _Req 8.3_
- [x] 5.5 Audit events for all sensitive actions. _Req 8.4_

## Phase 6: Frontend

- [x] 6.1 Typed API wrappers and Zod schemas in `frontend/src/api/`. _Req 4, 7_
- [x] 6.2 `AskHrPage`, `ChatPanel`, `AnswerCard`, feedback, escalate dialog; `OrientAssistant` links to Ask HR. _Req 4, 7, 10_
- [x] 6.3 Fallback banner and not-found state; loading and error states that never blank the page. _Req 6.2, 10.4_
- [x] 6.4 Policies page: Upload file, Index status badge (text + icon), Reindex, audience and review-date fields. _Req 1, 3.1_
- [x] 6.5 Insights tab and HR inbox. _Req 7.3, 8.3_
- [x] 6.6 Component, permission-state and axe tests. _Req 10, CB-AC-08_

## Phase 7: Documentation and rollout

- [x] 7.1 Update `frontend/src/lib/guideContent.ts` and `docs/USER_GUIDE.md` (keep in sync). Remove the statement that the HR assistant never uses AI once the KB backend is on.
- [ ] 7.2 Update `docs/code-tree` and threat model with new data flows. _Req 5_
- [ ] 7.3 Synthetic seed policies, labelled synthetic, for demo. _Data rule_
- [ ] 7.4 Tune chunk size, top-k and score threshold with a test question set; record results.
- [ ] 7.5 CloudWatch metrics and alarms: sync failures, empty-result rate, latency, guardrail blocks, Bedrock errors.
- [ ] 7.6 Enable in UAT, run acceptance gate CB-AC-01..08, then production after human release approval.

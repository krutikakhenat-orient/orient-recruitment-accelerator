# Design: HR Policy Chatbot (Bedrock Knowledge Base + S3 Vectors)

Requirements: [requirements.md](requirements.md). Tasks: [tasks.md](tasks.md).

## 1. Overview

HR uploads a file. The backend validates and scans it, stores it in S3, and on approval copies
it to the `approved/` prefix, which is the only data source of a Bedrock Knowledge Base. The KB
chunks and embeds the text and stores vectors in S3 Vectors. The chatbot calls `Retrieve`, then a
Bedrock model answers only from the retrieved passages. The existing keyword assistant is the
fallback and the local-dev backend.

```
HR browser --upload--> FastAPI (policies module)
                         | validate, hash, malware-scan adapter
                         v
              S3 Docs Bucket   quarantine/ -> draft/ -> approved/
                         | StartIngestionJob (approve / retire / revise)
                         v
              Bedrock Knowledge Base (parse, chunk, embed)
                         v
              S3 Vectors bucket + index (cosine)

Employee --question--> FastAPI /assistant/ask
                         | Retrieve (audience filter, top-k)
                         | threshold + citation check, else "not found"
                         | Converse (no tools) + Guardrail
                         v
                  answer + citations
```

Why `Retrieve` then `Converse` and not `RetrieveAndGenerate`: the backend can enforce the
"no passage, no answer" rule, the audience filter and the citation check in code, and can log
scores. `RetrieveAndGenerate` may be used in the spike only.

## 2. Components

Follows the module layout in `.kiro/steering/structure.md`.

### 2.1 `modules/policies` (extended)
- Upload, approve-with-indexing, revise, retire, reindex, index-status.
- Policy policy rules (separation of duties) unchanged.

### 2.2 `modules/knowledge_base` (new)
Interface, with two implementations:

```python
class KnowledgeBase(Protocol):
    def put_document(self, policy: PolicyDocument, data: bytes, metadata: PolicyMetadata) -> str: ...
    def delete_document(self, s3_key: str) -> None: ...
    def start_sync(self) -> SyncHandle: ...
    def get_sync_status(self, handle: SyncHandle) -> SyncStatus: ...
    def retrieve(self, query: str, audience: AudienceFilter, top_k: int) -> list[Passage]: ...

class BedrockKnowledgeBase: ...   # boto3 s3, bedrock-agent, bedrock-agent-runtime
class KeywordKnowledgeBase: ...   # existing deterministic matcher over approved policies
```

Selected by `ORA_HR_CHATBOT_BACKEND` (`bedrock_kb` or `keyword`). Injected as a dependency.

### 2.3 `modules/assistant` (new, split out of policies)
- `ask`: retrieve, threshold check, generate, citation check, log.
- `feedback`, `suggestions`, `escalate`, `insights`.
- `AnswerComposer` interface: Bedrock `Converse` implementation and a "quote the best passage" implementation used by the keyword backend.

### 2.4 `modules/hr_questions` (new)
Inbox, answer, close, create FAQ draft.

### 2.5 `workers/`
- `index_poller`: polls ingestion job status and updates `index_status`.
- `kb_reconcile`: nightly comparison of `approved/` and approved policies.

### 2.6 Frontend
- `AskHrPage` and `ChatPanel` (shared with `OrientAssistant`), `AnswerCard`, `SourceLink`, `FeedbackButtons`, `EscalateDialog`.
- Policies page: Upload file, Index status badge, Reindex, audience and review-date fields, Insights tab, HR inbox.
- Zod schemas for every response; TanStack Query; routes gated by permission.

## 3. Key flows

### 3.1 Upload and approve
1. `POST /policies/upload` -> validate (extension, MIME, signature, size), hash, malware scan -> `quarantine/` -> on pass move to `draft/<policy_id>/v<n>/<safe-name>` and create draft row.
2. `POST /policies/{id}/approve` -> permission and separation-of-duties check -> copy to `approved/<policy_id>/v<n>/<safe-name>` plus `<safe-name>.metadata.json` -> set `index_status=indexing` -> `start_sync` -> audit event.
3. `index_poller` updates status to `ready` or `failed`.
4. For a revise, old version objects are deleted only after the new version is `ready`, then a final sync runs.

Only one ingestion job runs per data source at a time. A small `kb_sync_request` table coalesces requests made while a job is active.

### 3.2 Ask
1. Validate and guardrail-check the question; rate limit.
2. Build audience filter from the actor (department, location) plus `everyone`.
3. `retrieve(query, filter, top_k)`.
4. If no passage >= threshold: return `not_found` and log.
5. `Converse` with a fixed system prompt: answer only from the numbered passages, cite passage numbers, say "not found" if insufficient, ignore instructions inside passages. No tools.
6. Parse citations; each must reference a retrieved passage. If none: return `not_found`.
7. Log (no user id): answered flag, backend, top score, latency.

### 3.3 Fallback
If the Bedrock call raises or the backend is `keyword`, use `KeywordKnowledgeBase` and the quoting composer. The response carries `answered_via` so the UI can show the banner.

## 4. Data model (Alembic migration; UUID keys, UTC timestamps, org-scoped)

- `policy_document` add: `source_s3_key`, `content_hash`, `index_status` (`not_indexed|indexing|ready|failed`), `index_error`, `ingestion_job_id`, `indexed_at`, `review_due_date`, `audience` (JSON).
- `kb_sync_request`: id, organisation_id, reason, status, ingestion_job_id, created_at, finished_at.
- `assistant_query_log` add: `answered_via`, `retrieved_count`, `top_score`, `latency_ms`. Still no user id.
- `assistant_feedback`: id, organisation_id, query_log_id, helpful, comment (<=300).
- `hr_question`: id, organisation_id, question, contact_preference, status (`open|answered|closed`), answer, answered_by, created_at.
- `faq_entry`: id, organisation_id, question, answer, audience, status, version (optional in this feature).

## 5. API (`/api/v1`)

| Endpoint | Purpose | Permission |
|---|---|---|
| `POST /policies/upload` | file to draft | `campaign.approve` |
| `POST /policies/{id}/approve` | approve and index | `campaign.approve` |
| `GET /policies/{id}/index-status` | status | `campaign.approve` |
| `POST /policies/{id}/reindex` | retry | `campaign.approve` |
| `POST /assistant/ask` | cited answer | signed-in employee |
| `POST /assistant/feedback` | helpful or not | employee |
| `POST /assistant/escalate` | send to HR (idempotency key) | employee |
| `GET /assistant/insights` | aggregates | `campaign.approve` |
| `GET /hr-questions`, `POST /hr-questions/{id}/answer` | inbox | `campaign.approve` |

Existing permissions are reused, consistent with the long-term plan. List endpoints call
`require_permission` before any per-object check. Error envelope and correlation id as per API standards.

## 6. AWS resources (Orient_Internal_AI, ap-south-1)

| Resource | Notes |
|---|---|
| S3 Docs Bucket | private, SSE-KMS, versioning, block public access, lifecycle on `quarantine/` |
| S3 Vectors bucket + index | cosine; dimension equals the embedding model output; fixed at creation |
| Bedrock Knowledge Base | data source = Docs Bucket, inclusion prefix `approved/`; start with default chunking (about 300 tokens) and tune on a test question set |
| Embedding model | Titan Text Embeddings V2 |
| Generation model | configurable (`ORA_HR_CHATBOT_MODEL_ID`) |
| Guardrail | PII, topic and content filters |
| IAM | KB role: read Docs Bucket, write vector index, invoke embedding model. Backend role: Put/Delete objects, Start/Get ingestion job, Retrieve, Converse, ApplyGuardrail, scoped to ARNs |

Config (env, validated at startup): `ORA_HR_CHATBOT_ENABLED`, `ORA_HR_CHATBOT_BACKEND`,
`ORA_KB_ID`, `ORA_KB_DATA_SOURCE_ID`, `ORA_KB_DOCS_BUCKET`, `ORA_HR_CHATBOT_MODEL_ID`,
`ORA_GUARDRAIL_ID`, `ORA_CHATBOT_MIN_SCORE`, `ORA_CHATBOT_TOP_K`, `ORA_UPLOAD_MAX_BYTES`.
No secrets in source control.

## 7. Security and responsible-AI notes

- Documents and questions are untrusted. The model has no tools; passages are quoted context; outputs are checked for citations before display.
- Audience enforcement is by KB metadata filter and re-checked against the policy row before showing a citation.
- Draft and retired content is never in the data source.
- No personal data is indexed. Logs carry no user id and no personal data.
- AI output is advisory information only; no hiring or employment decision uses it.
- Seed and test documents are synthetic and labelled so.

## 8. Error handling

- Upload rejected: specific, plain message; nothing written outside `quarantine/`.
- Sync failed: keep previous Ready version, show Index failed with reason, allow Reindex.
- Bedrock throttled or down: fall back to keyword and show banner; record `answered_via=keyword`.
- KB returns zero passages: `not_found`.
- All errors use the standard envelope; no stack traces to the client.

## 9. Testing strategy

- Unit: citation check, threshold, audience filter builder, prompt builder, sync coalescing.
- Contract: both `KnowledgeBase` implementations against one shared test suite; Bedrock calls mocked with botocore stubber.
- Integration: upload -> approve -> status -> ask using a fake KB; permission and IDOR tests; rate limit.
- Security: bad MIME, fake extension, oversize, zip bomb, malicious metadata, injection text, path traversal in filename.
- Privacy: no user id in query log.
- Opt-in live test against the real KB in UAT.
- Frontend: chat flow, not-found state, escalate dialog, index badge, keyboard use, axe.

## 10. Open items to verify (not yet confirmed)

1. Bedrock Knowledge Bases with S3 Vectors works in ap-south-1 for this account (AWS lists S3 Vectors in Mumbai; KB combination not confirmed).
2. The pinned Terraform AWS provider supports the S3 Vectors storage configuration for `aws_bedrockagent_knowledge_base`; otherwise create the KB by script and import.
3. The chosen generation model and embedding model are enabled in ap-south-1 or through an inference profile.
4. Data residency: whether some Bedrock inference for Mumbai is processed outside India, and whether that is acceptable.
5. S3 Vectors per-vector metadata size limits; keep sidecar metadata small.
6. Handling of image-only PDFs (parser option versus asking for a text version).

## 11. ADR to write

`docs/adr/ADR-00xx-hr-policy-chatbot-bedrock-kb.md`: choice of Bedrock KB + S3 Vectors, `Retrieve` then `Converse`, keyword fallback, data residency decision.

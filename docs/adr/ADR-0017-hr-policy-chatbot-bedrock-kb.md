# ADR-0017: HR policy chatbot on Bedrock Knowledge Base + S3 Vectors, with keyword fallback

**Status:** Accepted (Phase 0 trial done 2026-11-13; open items below) |
**Spec:** `.kiro/specs/hr-policy-chatbot` | **Evidence:** `docs/hr-chatbot-phase0-findings.md`

## Context

Employees ask HR policy questions. Answers must come only from approved policy, cite their
source, respect who a policy is for, keep drafts out, survive hostile document text, and keep
working when no AI service is available (product principles 1-3, 15; responsible-ai.md).
The deployment is serverless (Lambda + Aurora Serverless with auto-pause) in account
Orient_Internal_AI, ap-south-1, and idle cost matters.

## Decision

1. **Retrieval:** Amazon Bedrock Knowledge Base whose only data source is the `approved/`
   prefix of a private Docs Bucket; vectors in **Amazon S3 Vectors** (1024-dim, cosine);
   embeddings **Titan Text Embeddings V2**. Each object has a small `.metadata.json` sidecar
   (`organisation_id`, `policy_id`, `version`, `title`, `kind`, `audience`), used for an
   `equals` organisation filter plus a `listContains` audience filter.
2. **Retrieve, then Converse** (not RetrieveAndGenerate), so the backend enforces in code:
   the relevance threshold (default 0.65), a re-check of every passage against the policy row
   (organisation, audience, still searchable), and "no valid citation, no answer".
3. **Generation:** Bedrock Converse with a fixed system prompt, **no tools**, temperature 0,
   passages as escaped, numbered data. Default model profile
   `in.anthropic.claude-haiku-4-5-20251001-v1:0` (India-only routing). Configurable via
   `ORA_HR_CHATBOT_MODEL_ID`.
4. **Guardrail:** Bedrock Guardrail (PII anonymise, content filters, prompt attack) applied to
   the question (`ApplyGuardrail` and `guardContent`) and to the output. **Not** to the quoted
   passages: one hostile document would otherwise block every answer (Phase 0 finding).
5. **Fallback:** the deterministic keyword knowledge base behind the same `KnowledgeBase`
   interface. It is the default (`ORA_HR_CHATBOT_BACKEND=keyword`), the local-dev backend, and
   the automatic fallback when Bedrock fails; replies say which backend answered.
6. **Infrastructure:** Terraform (AWS provider 6.72 supports every resource), applied locally
   per environment with `scripts\tf.ps1 <uat|prod>`, UAT first. Index polling and nightly
   reconcile run as ops-Lambda actions on EventBridge Scheduler.

## Alternatives considered

- **OpenSearch Serverless as the vector store:** mature and fully featured, but it carries a
  fixed minimum monthly charge even when idle, far above this workload's budget. Rejected.
- **Aurora pgvector (existing cluster):** no new store, but it would keep Aurora awake for
  every question and break auto-pause savings, and the KB integration needs extra setup.
  Possible later if S3 Vectors limits bite.
- **RetrieveAndGenerate:** less code, but the backend could not enforce the threshold,
  audience re-check and citation rule itself. Kept for experiments only.
- **Nova Lite via `apac.*` profile:** cheaper per token, but routes outside India. Rejected
  while data residency is undecided (requirements.md open question 3).
- **Keyword only:** no AI risk or cost, but poor recall on paraphrased questions. Kept as the
  default and fallback.

## Consequences

- Idle cost is near zero (S3 storage, a KMS key, S3 Vectors storage); cost grows with questions
  answered. Rough estimate for about 50 policies and 1,000 questions a month: a few US dollars,
  dominated by the generation model (unverified list-price estimate; confirm with Cost
  Explorer after a month in UAT).
- Two moving parts per approval (object copy + ingestion job); handled by sync coalescing,
  index status (Indexing / Ready / Index failed), Reindex and the nightly reconcile.
- Answers can only be as good as retrieval; the threshold and top-k need tuning on real
  policies before production.
- AI output stays advisory information; it never makes or triggers an HR decision.

## Open items

- requirements.md open questions 1, 2, 4-6 (who may ask; department/location audiences need
  profile fields; final model choice; email for "Send to HR"; Hindi).
- Confirm where Guardrail evaluation is processed for ap-south-1 before production.
- Verify PDF page citations, chunking and metadata limits in UAT (findings, "Not verified").

# HR policy chatbot (ADR-0017, docs/hr-chatbot-phase0-findings.md, .kiro/specs/hr-policy-chatbot).
# Everything here exists only when var.hr_chatbot_enabled = true. With it false the API keeps the
# keyword assistant and none of these resources are created.
#
#   Docs bucket (KMS, versioned)  quarantine/ -> draft/ -> approved/   (only approved/ is indexed)
#   Bedrock Knowledge Base (Titan Embed V2) -> S3 Vectors index (1024 dims, cosine)
#   Bedrock Guardrail (question + output; content filters + prompt attack), generation model
#   var.hr_chatbot_model_id
#   EventBridge Scheduler: one nightly ops call (settle syncs + reconcile)

locals {
  chatbot    = var.hr_chatbot_enabled ? 1 : 0
  account_id = data.aws_caller_identity.current.account_id

  embedding_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/${var.hr_chatbot_embedding_model_id}"
  # Foundation-model ARN (on-demand). An inference-profile id (e.g. "in.anthropic...") would also
  # need the profile ARN; keep the default on-demand model unless ADR-0017 changes.
  generation_model_arn = "arn:aws:bedrock:${var.region}::foundation-model/${var.hr_chatbot_model_id}"

  chatbot_env = var.hr_chatbot_enabled ? {
    ORA_HR_CHATBOT_ENABLED  = "true"
    ORA_HR_CHATBOT_BACKEND  = "bedrock_kb"
    ORA_KB_ID               = aws_bedrockagent_knowledge_base.hr[0].id
    ORA_KB_DATA_SOURCE_ID   = aws_bedrockagent_data_source.approved[0].data_source_id
    ORA_KB_DOCS_BUCKET      = aws_s3_bucket.hr_docs[0].bucket
    ORA_KB_REGION           = var.region
    ORA_HR_CHATBOT_MODEL_ID = var.hr_chatbot_model_id
    ORA_GUARDRAIL_ID        = aws_bedrock_guardrail.hr[0].guardrail_id
    ORA_GUARDRAIL_VERSION   = aws_bedrock_guardrail_version.hr[0].version
    ORA_CHATBOT_MIN_SCORE   = tostring(var.hr_chatbot_min_score)
  } : {}
}

# ---------------------------------------------------------------- encryption key (Req 9.1)
resource "aws_kms_key" "hr_docs" {
  count                   = local.chatbot
  description             = "${local.prefix} HR policy documents (docs bucket)"
  enable_key_rotation     = true
  deletion_window_in_days = 30
}

resource "aws_kms_alias" "hr_docs" {
  count         = local.chatbot
  name          = "alias/${local.prefix}-hr-docs"
  target_key_id = aws_kms_key.hr_docs[0].key_id
}

# ---------------------------------------------------------------- docs bucket (private)
resource "aws_s3_bucket" "hr_docs" {
  count  = local.chatbot
  bucket = "${local.prefix}-hr-docs-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "hr_docs" {
  count                   = local.chatbot
  bucket                  = aws_s3_bucket.hr_docs[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "hr_docs" {
  count  = local.chatbot
  bucket = aws_s3_bucket.hr_docs[0].id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "hr_docs" {
  count  = local.chatbot
  bucket = aws_s3_bucket.hr_docs[0].id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.hr_docs[0].arn
    }
    bucket_key_enabled = true # fewer KMS requests (cost)
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "hr_docs" {
  count  = local.chatbot
  bucket = aws_s3_bucket.hr_docs[0].id

  # Uploads that failed validation/scan are deleted by the app; this is the safety net.
  rule {
    id     = "expire-quarantine"
    status = "Enabled"
    filter { prefix = "quarantine/" }
    expiration { days = 1 }
    noncurrent_version_expiration { noncurrent_days = 1 }
  }
  # Old copies of replaced or retired files.
  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration { noncurrent_days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
  depends_on = [aws_s3_bucket_versioning.hr_docs]
}

resource "aws_s3_bucket_policy" "hr_docs_tls_only" {
  count  = local.chatbot
  bucket = aws_s3_bucket.hr_docs[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.hr_docs[0].arn, "${aws_s3_bucket.hr_docs[0].arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
  depends_on = [aws_s3_bucket_public_access_block.hr_docs]
}

# ---------------------------------------------------------------- vector store (S3 Vectors)
resource "aws_s3vectors_vector_bucket" "hr" {
  count              = local.chatbot
  vector_bucket_name = "${local.prefix}-hr-vectors-${local.account_id}"
}

resource "aws_s3vectors_index" "hr" {
  count              = local.chatbot
  vector_bucket_name = aws_s3vectors_vector_bucket.hr[0].vector_bucket_name
  index_name         = "policies"
  data_type          = "float32"
  dimension          = 1024 # Titan Text Embeddings V2; fixed at creation
  distance_metric    = "cosine"

  # Bedrock stores chunk text and its own metadata here; keep them out of the small
  # filterable-metadata budget (filters use organisation_id and audience only).
  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
}

# ---------------------------------------------------------------- Knowledge Base role
resource "aws_iam_role" "hr_kb" {
  count = local.chatbot
  name  = "${local.prefix}-hr-kb"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = {
        StringEquals = { "aws:SourceAccount" = local.account_id }
        ArnLike      = { "aws:SourceArn" = "arn:aws:bedrock:${var.region}:${local.account_id}:knowledge-base/*" }
      }
    }]
  })
}

resource "aws_iam_role_policy" "hr_kb" {
  count = local.chatbot
  name  = "kb-access"
  role  = aws_iam_role.hr_kb[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # The KB can read ONLY approved/ (drafts and quarantine are never indexed, Req 2.1).
        Sid       = "ListApproved"
        Effect    = "Allow"
        Action    = ["s3:ListBucket"]
        Resource  = aws_s3_bucket.hr_docs[0].arn
        Condition = { StringLike = { "s3:prefix" = ["approved/*"] } }
      },
      {
        Sid      = "ReadApproved"
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.hr_docs[0].arn}/approved/*"
      },
      {
        Sid      = "DecryptDocs"
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = aws_kms_key.hr_docs[0].arn
      },
      {
        Sid      = "Embed"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.embedding_model_arn
      },
      {
        Sid    = "VectorIndex"
        Effect = "Allow"
        Action = [
          "s3vectors:PutVectors", "s3vectors:GetVectors", "s3vectors:DeleteVectors",
          "s3vectors:QueryVectors", "s3vectors:GetIndex"
        ]
        Resource = aws_s3vectors_index.hr[0].index_arn
      }
    ]
  })
}

# ---------------------------------------------------------------- Knowledge Base + data source
resource "aws_bedrockagent_knowledge_base" "hr" {
  count       = local.chatbot
  name        = "${local.prefix}-hr-policies"
  description = "Approved HR policies (approved/ prefix only). ADR-0017."
  role_arn    = aws_iam_role.hr_kb[0].arn

  knowledge_base_configuration {
    type = "VECTOR"
    vector_knowledge_base_configuration {
      embedding_model_arn = local.embedding_model_arn
      embedding_model_configuration {
        bedrock_embedding_model_configuration {
          dimensions          = 1024
          embedding_data_type = "FLOAT32"
        }
      }
    }
  }

  storage_configuration {
    type = "S3_VECTORS"
    s3_vectors_configuration {
      index_arn = aws_s3vectors_index.hr[0].index_arn
    }
  }

  # The role policy must exist before Bedrock validates the role (Phase 0: first attempt fails
  # with "unable to assume the given role" otherwise).
  depends_on = [aws_iam_role_policy.hr_kb]
}

resource "aws_bedrockagent_data_source" "approved" {
  count                = local.chatbot
  knowledge_base_id    = aws_bedrockagent_knowledge_base.hr[0].id
  name                 = "approved-only"
  data_deletion_policy = "DELETE" # removing an object removes its vectors on the next sync

  data_source_configuration {
    type = "S3"
    s3_configuration {
      bucket_arn         = aws_s3_bucket.hr_docs[0].arn
      inclusion_prefixes = ["approved/"]
    }
  }
}

# ---------------------------------------------------------------- Guardrail (Req 5.3)
resource "aws_bedrock_guardrail" "hr" {
  count                     = local.chatbot
  name                      = "${local.prefix}-hr-chatbot"
  description               = "HR policy chatbot: questions and answers. Quoted passages are not guarded (ADR-0017)."
  blocked_input_messaging   = "I can't help with that question here. Please contact HR directly."
  blocked_outputs_messaging = "I can't help with that question here. Please contact HR directly."

  content_policy_config {
    dynamic "filters_config" {
      for_each = ["HATE", "INSULTS", "SEXUAL", "VIOLENCE", "MISCONDUCT"]
      content {
        type            = filters_config.value
        input_strength  = "HIGH"
        output_strength = "HIGH"
      }
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }
  # No PII ANONYMIZE rule on purpose: Bedrock reports an anonymisation as GUARDRAIL_INTERVENED,
  # which the app treats as "blocked", so a question containing an email would be refused.
  # PII is masked by the app before logging (assistant/guard.py scrub_pii) and policies hold no
  # personal data. Every rule here BLOCKS, so "intervened" always means "blocked".
}

resource "aws_bedrock_guardrail_version" "hr" {
  count         = local.chatbot
  guardrail_arn = aws_bedrock_guardrail.hr[0].guardrail_arn
  description   = "Managed by Terraform"
}

# ---------------------------------------------------------------- API/ops Lambda permissions
resource "aws_iam_role_policy" "lambda_hr_chatbot" {
  count = local.chatbot
  name  = "hr-chatbot"
  role  = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "DocsObjects"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
        Resource = "${aws_s3_bucket.hr_docs[0].arn}/*"
      },
      {
        # Reconcile lists approved/; without ListBucket a missing key returns 403, not 404.
        Sid      = "DocsList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.hr_docs[0].arn
      },
      {
        Sid      = "DocsKey"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.hr_docs[0].arn
      },
      {
        Sid      = "KnowledgeBase"
        Effect   = "Allow"
        Action   = ["bedrock:Retrieve", "bedrock:StartIngestionJob", "bedrock:GetIngestionJob"]
        Resource = aws_bedrockagent_knowledge_base.hr[0].arn
      },
      {
        # Converse needs InvokeModel on the generation model. No tools are configured.
        Sid      = "GenerateAnswer"
        Effect   = "Allow"
        Action   = ["bedrock:InvokeModel"]
        Resource = local.generation_model_arn
      },
      {
        Sid      = "Guardrail"
        Effect   = "Allow"
        Action   = ["bedrock:ApplyGuardrail"]
        Resource = aws_bedrock_guardrail.hr[0].guardrail_arn
      }
    ]
  })
}

# ---------------------------------------------------------------- nightly settle + reconcile
resource "aws_iam_role" "hr_scheduler" {
  count = local.chatbot
  name  = "${local.prefix}-hr-scheduler"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "hr_scheduler" {
  count = local.chatbot
  name  = "invoke-ops"
  role  = aws_iam_role.hr_scheduler[0].id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["lambda:InvokeFunction"]
      Resource = [aws_lambda_function.ops.arn, "${aws_lambda_function.ops.arn}:*"]
    }]
  })
}

resource "aws_scheduler_schedule" "hr_reconcile" {
  count                        = local.chatbot
  name                         = "${local.prefix}-hr-kb-reconcile"
  description                  = "HR chatbot: settle finished syncs and repair approved/ (once a day so Aurora can stay paused)"
  schedule_expression          = var.hr_chatbot_reconcile_cron
  schedule_expression_timezone = "UTC"

  flexible_time_window { mode = "OFF" }

  target {
    arn      = aws_lambda_function.ops.arn
    role_arn = aws_iam_role.hr_scheduler[0].arn
    input    = jsonencode({ action = "kb_reconcile" })
    retry_policy { maximum_retry_attempts = 2 }
  }
}

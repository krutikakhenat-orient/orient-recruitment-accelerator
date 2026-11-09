# Backend release pipeline. See docs/backend-cicd-pipeline.md.
#
#   CodeCommit main --(EventBridge)--> CodePipeline V2 (QUEUED)
#     Source  -> Verify (Tests | Security) -> Build -> Approve* -> Deploy*
#   * skipped when the commit changes nothing the Lambda runs (Build.BACKEND_CHANGED != "true").
#
# The pipeline releases Lambda CODE only. Infrastructure stays Terraform-managed and applied
# locally (terraform/), so no pipeline role can create or change infrastructure.

data "aws_caller_identity" "current" {}

data "terraform_remote_state" "app" {
  backend = "s3"
  config = {
    bucket  = var.state_bucket
    key     = var.app_state_key
    region  = var.region
    profile = var.aws_profile != "" ? var.aws_profile : null
  }
}

locals {
  prefix        = "${var.name}-${var.environment}"
  account_id    = data.aws_caller_identity.current.account_id
  app           = data.terraform_remote_state.app.outputs
  buildspec_dir = "Orient_Internal_AI_Deployment/buildspec"
  image         = "aws/codebuild/amazonlinux-x86_64-standard:5.0"
  snapshot_arn  = "arn:aws:rds:${var.region}:${local.account_id}:cluster-snapshot:ora-pre-*"

  # Approve and Deploy run only when Build says the commit changes Lambda code (or FORCE_RELEASE).
  backend_changed_rule = {
    Variable = "#{Build.BACKEND_CHANGED}"
    Value    = "true"
    Operator = "EQ"
  }

  snapshot_tags = [
    { Key = "Project", Value = "orient-recruitment-accelerator" },
    { Key = "Application", Value = "HR Accelerator" },
    { Key = "Environment", Value = var.environment },
    { Key = "Owner", Value = "sumanpramanik@orientindia.net" },
    { Key = "CostCenter", Value = "Orient_Internal_AI" },
    { Key = "ManagedBy", Value = "codepipeline" },
  ]
}

# ---------------------------------------------------------------- artifact bucket (private)
resource "aws_s3_bucket" "pipeline" {
  bucket = "${local.prefix}-pipeline-${local.account_id}"
}

resource "aws_s3_bucket_public_access_block" "pipeline" {
  bucket                  = aws_s3_bucket.pipeline.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "pipeline" {
  bucket = aws_s3_bucket.pipeline.id
  rule {
    id     = "expire-artifacts"
    status = "Enabled"
    filter {}
    expiration { days = 30 }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}

resource "aws_s3_bucket_policy" "pipeline_tls_only" {
  bucket = aws_s3_bucket.pipeline.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.pipeline.arn, "${aws_s3_bucket.pipeline.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---------------------------------------------------------------- release bookkeeping
# Last commit released to production. Build diffs against it; Deploy updates it.
resource "aws_ssm_parameter" "last_release" {
  name        = "/${local.prefix}/release/last-commit"
  description = "Last backend commit released by ${local.prefix}-backend (written by the Deploy stage)"
  type        = "String"
  value       = "none"

  lifecycle {
    ignore_changes = [value]
  }
}

# ---------------------------------------------------------------- approval notifications
resource "aws_sns_topic" "approvals" {
  name = "${local.prefix}-release-approvals"
}

resource "aws_sns_topic_subscription" "approvers" {
  for_each  = toset(var.approver_emails)
  topic_arn = aws_sns_topic.approvals.arn
  protocol  = "email"
  endpoint  = each.value
}

resource "aws_cloudwatch_log_group" "codebuild" {
  name              = "/aws/codebuild/${local.prefix}-backend"
  retention_in_days = var.log_retention_days
}

# ---------------------------------------------------------------- IAM
data "aws_iam_policy_document" "codebuild_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["codebuild.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

# Tests, Security, Build: read source, write logs/artifacts, read the release marker. No deploy rights.
resource "aws_iam_role" "ci" {
  name               = "${local.prefix}-pipeline-ci"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

resource "aws_iam_role_policy" "ci" {
  name = "ci"
  role = aws_iam_role.ci.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.codebuild.arn}:*"
      },
      {
        Sid      = "PipelineArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
        Resource = "${aws_s3_bucket.pipeline.arn}/*"
      },
      {
        Sid      = "PipelineBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.pipeline.arn
      },
      {
        # Full clone of the source (git diff against the last released commit).
        Sid      = "SourceClone"
        Effect   = "Allow"
        Action   = ["codecommit:GitPull"]
        Resource = local.app.codecommit_repo_arn
      },
      {
        Sid      = "ReadReleaseMarker"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter"]
        Resource = aws_ssm_parameter.last_release.arn
      },
    ]
  })
}

# Deploy: change Lambda CODE and the alias of these two functions only. Cannot create or change
# infrastructure, IAM, configuration or environment variables.
resource "aws_iam_role" "deploy" {
  name               = "${local.prefix}-pipeline-deploy"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

resource "aws_iam_role_policy" "deploy" {
  name = "deploy"
  role = aws_iam_role.deploy.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "Logs"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.codebuild.arn}:*"
      },
      {
        Sid      = "PipelineArtifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion"]
        Resource = "${aws_s3_bucket.pipeline.arn}/*"
      },
      {
        Sid      = "PipelineBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketAcl", "s3:GetBucketLocation"]
        Resource = aws_s3_bucket.pipeline.arn
      },
      {
        # Release packages. Lambda reads the object with the caller's permissions.
        Sid      = "ReleasePackages"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "arn:aws:s3:::${local.app.artifacts_bucket}/releases/*"
      },
      {
        Sid    = "ReleaseLambdaCode"
        Effect = "Allow"
        Action = [
          "lambda:UpdateFunctionCode",
          "lambda:PublishVersion",
          "lambda:GetFunction",
          "lambda:GetFunctionConfiguration",
          "lambda:InvokeFunction",
          "lambda:GetAlias",
          "lambda:UpdateAlias",
        ]
        Resource = [
          local.app.api_function_arn, "${local.app.api_function_arn}:*",
          local.app.ops_function_arn, "${local.app.ops_function_arn}:*",
        ]
      },
      {
        # Backup before a release that contains database migrations.
        Sid      = "PreMigrationSnapshot"
        Effect   = "Allow"
        Action   = ["rds:CreateDBClusterSnapshot", "rds:AddTagsToResource"]
        Resource = [local.app.db_cluster_arn, local.snapshot_arn]
      },
      {
        Sid      = "WaitForSnapshot"
        Effect   = "Allow"
        Action   = ["rds:DescribeDBClusterSnapshots"]
        Resource = "*"
      },
      {
        Sid      = "ReleaseMarker"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:PutParameter"]
        Resource = aws_ssm_parameter.last_release.arn
      },
    ]
  })
}

resource "aws_iam_role" "pipeline" {
  name = "${local.prefix}-pipeline"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "codepipeline.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "pipeline" {
  name = "pipeline"
  role = aws_iam_role.pipeline.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "Source"
        Effect = "Allow"
        Action = [
          "codecommit:GetBranch",
          "codecommit:GetCommit",
          "codecommit:GetRepository",
          "codecommit:UploadArchive",
          "codecommit:GetUploadArchiveStatus",
          "codecommit:CancelUploadArchive",
        ]
        Resource = local.app.codecommit_repo_arn
      },
      {
        Sid      = "Artifacts"
        Effect   = "Allow"
        Action   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject"]
        Resource = "${aws_s3_bucket.pipeline.arn}/*"
      },
      {
        Sid      = "ArtifactBucket"
        Effect   = "Allow"
        Action   = ["s3:GetBucketVersioning", "s3:GetBucketLocation", "s3:ListBucket"]
        Resource = aws_s3_bucket.pipeline.arn
      },
      {
        Sid    = "Builds"
        Effect = "Allow"
        Action = ["codebuild:StartBuild", "codebuild:BatchGetBuilds"]
        Resource = [
          aws_codebuild_project.tests.arn,
          aws_codebuild_project.security.arn,
          aws_codebuild_project.build.arn,
          aws_codebuild_project.deploy.arn,
        ]
      },
      {
        Sid      = "ApprovalNotice"
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.approvals.arn
      },
    ]
  })
}

# ---------------------------------------------------------------- CodeBuild projects
resource "aws_codebuild_project" "tests" {
  name          = "${local.prefix}-backend-tests"
  description   = "Lint, type check, unit/integration tests, migrations on a throwaway PostgreSQL"
  service_role  = aws_iam_role.ci.arn
  build_timeout = 30

  artifacts { type = "CODEPIPELINE" }
  source {
    type      = "CODEPIPELINE"
    buildspec = "${local.buildspec_dir}/tests.yml"
  }
  environment {
    compute_type = "BUILD_GENERAL1_MEDIUM"
    image        = local.image
    type         = "LINUX_CONTAINER"
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild.name
      stream_name = "tests"
    }
  }
}

resource "aws_codebuild_project" "security" {
  name          = "${local.prefix}-backend-security"
  description   = "Secret scan (gitleaks) and static security analysis (bandit)"
  service_role  = aws_iam_role.ci.arn
  build_timeout = 15

  artifacts { type = "CODEPIPELINE" }
  source {
    type      = "CODEPIPELINE"
    buildspec = "${local.buildspec_dir}/security.yml"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = local.image
    type         = "LINUX_CONTAINER"
    environment_variable {
      name  = "GITLEAKS_VERSION"
      value = var.gitleaks_version
    }
    environment_variable {
      name  = "GITLEAKS_SHA256"
      value = var.gitleaks_linux_x64_sha256
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild.name
      stream_name = "security"
    }
  }
}

resource "aws_codebuild_project" "build" {
  name          = "${local.prefix}-backend-build"
  description   = "Detect backend changes, build the Lambda package, audit dependencies"
  service_role  = aws_iam_role.ci.arn
  build_timeout = 20

  artifacts { type = "CODEPIPELINE" }
  source {
    type      = "CODEPIPELINE"
    buildspec = "${local.buildspec_dir}/build.yml"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = local.image
    type         = "LINUX_CONTAINER"
    environment_variable {
      name  = "RELEASE_PARAM"
      value = aws_ssm_parameter.last_release.name
    }
    environment_variable {
      name  = "PIP_AUDIT_ENFORCE"
      value = tostring(var.pip_audit_enforce)
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild.name
      stream_name = "build"
    }
  }
}

# The Deploy input is the Build artifact, which carries deploy.yml and release.py from the commit.
resource "aws_codebuild_project" "deploy" {
  name          = "${local.prefix}-backend-deploy"
  description   = "Release the Lambda code: publish, migrate, test, switch alias, smoke test, roll back on failure"
  service_role  = aws_iam_role.deploy.arn
  build_timeout = 60

  artifacts { type = "CODEPIPELINE" }
  source {
    type      = "CODEPIPELINE"
    buildspec = "deploy.yml"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = local.image
    type         = "LINUX_CONTAINER"
    environment_variable {
      name  = "API_FUNCTION"
      value = local.app.api_function_name
    }
    environment_variable {
      name  = "OPS_FUNCTION"
      value = local.app.ops_function_name
    }
    environment_variable {
      name  = "API_ALIAS"
      value = local.app.api_alias_name
    }
    environment_variable {
      name  = "APP_ARTIFACT_BUCKET"
      value = local.app.artifacts_bucket
    }
    environment_variable {
      name  = "DB_CLUSTER_ID"
      value = local.app.db_cluster_id
    }
    environment_variable {
      name  = "API_URL"
      value = local.app.api_url
    }
    environment_variable {
      name  = "RELEASE_PARAM"
      value = aws_ssm_parameter.last_release.name
    }
    environment_variable {
      name  = "SNAPSHOT_TAGS"
      value = jsonencode(local.snapshot_tags)
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild.name
      stream_name = "deploy"
    }
  }
}

# ---------------------------------------------------------------- pipeline
resource "aws_codepipeline" "backend" {
  name           = "${local.prefix}-backend"
  role_arn       = aws_iam_role.pipeline.arn
  pipeline_type  = "V2"
  execution_mode = "QUEUED"

  artifact_store {
    location = aws_s3_bucket.pipeline.bucket
    type     = "S3"
  }

  variable {
    name          = "FORCE_RELEASE"
    default_value = "false"
    description   = "true: release even if no backend code changed (e.g. after a Terraform config change)"
  }

  stage {
    name = "Source"
    action {
      name             = "Source"
      category         = "Source"
      owner            = "AWS"
      provider         = "CodeCommit"
      version          = "1"
      namespace        = "SourceVariables"
      output_artifacts = ["SourceOutput"]
      configuration = {
        RepositoryName       = local.app.codecommit_repo_name
        BranchName           = var.branch
        PollForSourceChanges = "false"
        OutputArtifactFormat = "CODEBUILD_CLONE_REF"
      }
    }
  }

  stage {
    name = "Verify"
    action {
      name            = "Tests"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      run_order       = 1
      input_artifacts = ["SourceOutput"]
      configuration   = { ProjectName = aws_codebuild_project.tests.name }
    }
    action {
      name            = "Security"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      run_order       = 1
      input_artifacts = ["SourceOutput"]
      configuration   = { ProjectName = aws_codebuild_project.security.name }
    }
  }

  stage {
    name = "Build"
    action {
      name             = "Package"
      category         = "Build"
      owner            = "AWS"
      provider         = "CodeBuild"
      version          = "1"
      namespace        = "Build"
      input_artifacts  = ["SourceOutput"]
      output_artifacts = ["BuildOutput"]
      configuration = {
        ProjectName = aws_codebuild_project.build.name
        EnvironmentVariables = jsonencode([
          { name = "FORCE_RELEASE", value = "#{variables.FORCE_RELEASE}", type = "PLAINTEXT" },
        ])
      }
    }
  }

  stage {
    name = "Approve"
    before_entry {
      condition {
        result = "SKIP"
        rule {
          name = "BackendChanged"
          rule_type_id {
            category = "Rule"
            owner    = "AWS"
            provider = "VariableCheck"
            version  = "1"
          }
          configuration = local.backend_changed_rule
        }
      }
    }
    action {
      name     = "ReleaseApproval"
      category = "Approval"
      owner    = "AWS"
      provider = "Manual"
      version  = "1"
      configuration = {
        NotificationArn = aws_sns_topic.approvals.arn
        CustomData      = "Backend release #{Build.COMMIT_SHORT}: #{Build.SUMMARY}. Full details: Build stage log (release.json). Approve only if new migrations keep the previous version working."
      }
    }
  }

  stage {
    name = "Deploy"
    before_entry {
      condition {
        result = "SKIP"
        rule {
          name = "BackendChanged"
          rule_type_id {
            category = "Rule"
            owner    = "AWS"
            provider = "VariableCheck"
            version  = "1"
          }
          configuration = local.backend_changed_rule
        }
      }
    }
    action {
      name            = "Release"
      category        = "Build"
      owner           = "AWS"
      provider        = "CodeBuild"
      version         = "1"
      input_artifacts = ["BuildOutput"]
      configuration   = { ProjectName = aws_codebuild_project.deploy.name }
    }
  }
}

# ---------------------------------------------------------------- trigger: push to main
resource "aws_iam_role" "events" {
  name = "${local.prefix}-pipeline-trigger"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "events.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "events" {
  name = "start-pipeline"
  role = aws_iam_role.events.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["codepipeline:StartPipelineExecution"]
      Resource = aws_codepipeline.backend.arn
    }]
  })
}

resource "aws_cloudwatch_event_rule" "main_push" {
  name        = "${local.prefix}-backend-release-on-push"
  description = "Start ${local.prefix}-backend when CodeCommit ${var.branch} changes"
  event_pattern = jsonencode({
    source        = ["aws.codecommit"]
    "detail-type" = ["CodeCommit Repository State Change"]
    resources     = [local.app.codecommit_repo_arn]
    detail = {
      event         = ["referenceCreated", "referenceUpdated"]
      referenceType = ["branch"]
      referenceName = [var.branch]
    }
  })
}

resource "aws_cloudwatch_event_target" "pipeline" {
  rule     = aws_cloudwatch_event_rule.main_push.name
  arn      = aws_codepipeline.backend.arn
  role_arn = aws_iam_role.events.arn
}

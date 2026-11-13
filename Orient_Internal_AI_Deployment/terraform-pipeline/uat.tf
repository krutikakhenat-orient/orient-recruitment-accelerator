# UAT release and production promotion for the ora-release pipeline.
#   deploy_uat : releases the Lambda code to the UAT stack only (same rights as the production
#                deploy role, scoped to ora-uat-* resources).
#   promote    : fast-forwards CodeCommit `main` to the commit that passed UAT. It can push only
#                to refs/heads/main, cannot force-push or delete branches, and has no AWS rights.

locals {
  uat_snapshot_tags = [for t in local.snapshot_tags : t.Key == "Environment" ? { Key = t.Key, Value = "uat" } : t]
}

# ---------------------------------------------------------------- UAT deploy
resource "aws_iam_role" "deploy_uat" {
  name               = "${local.uat_prefix}-pipeline-deploy"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

resource "aws_iam_role_policy" "deploy_uat" {
  name = "deploy"
  role = aws_iam_role.deploy_uat.id
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
        Sid      = "ReleasePackages"
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "arn:aws:s3:::${local.uat.artifacts_bucket}/releases/*"
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
          local.uat.api_function_arn, "${local.uat.api_function_arn}:*",
          local.uat.ops_function_arn, "${local.uat.ops_function_arn}:*",
        ]
      },
      {
        Sid      = "PreMigrationSnapshot"
        Effect   = "Allow"
        Action   = ["rds:CreateDBClusterSnapshot", "rds:AddTagsToResource"]
        Resource = [local.uat.db_cluster_arn, local.snapshot_arn]
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
        Resource = aws_ssm_parameter.last_release_uat.arn
      },
    ]
  })
}

resource "aws_codebuild_project" "deploy_uat" {
  name          = "${local.uat_prefix}-backend-deploy"
  description   = "Release the Lambda code to UAT: publish, migrate, test, switch alias, smoke test, roll back on failure"
  service_role  = aws_iam_role.deploy_uat.arn
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
      value = local.uat.api_function_name
    }
    environment_variable {
      name  = "OPS_FUNCTION"
      value = local.uat.ops_function_name
    }
    environment_variable {
      name  = "API_ALIAS"
      value = local.uat.api_alias_name
    }
    environment_variable {
      name  = "APP_ARTIFACT_BUCKET"
      value = local.uat.artifacts_bucket
    }
    environment_variable {
      name  = "DB_CLUSTER_ID"
      value = local.uat.db_cluster_id
    }
    environment_variable {
      name  = "API_URL"
      value = local.uat.api_url
    }
    environment_variable {
      name  = "RELEASE_PARAM"
      value = aws_ssm_parameter.last_release_uat.name
    }
    environment_variable {
      name  = "SNAPSHOT_TAGS"
      value = jsonencode(local.uat_snapshot_tags)
    }
    environment_variable {
      name  = "RELEASE_TARGET"
      value = "uat"
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild.name
      stream_name = "deploy-uat"
    }
  }
}

# ---------------------------------------------------------------- promote main
resource "aws_iam_role" "promote" {
  name               = "${var.name}-pipeline-promote"
  assume_role_policy = data.aws_iam_policy_document.codebuild_assume.json
}

resource "aws_iam_role_policy" "promote" {
  name = "promote"
  role = aws_iam_role.promote.id
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
        Sid      = "CloneSource"
        Effect   = "Allow"
        Action   = ["codecommit:GitPull"]
        Resource = local.app.codecommit_repo_arn
      },
      {
        # git push first calls without a reference, so the allow itself is unconditional...
        Sid      = "PushToRepository"
        Effect   = "Allow"
        Action   = ["codecommit:GitPush"]
        Resource = local.app.codecommit_repo_arn
      },
      {
        # ...and any reference other than main is denied. Non-fast-forward pushes are rejected by
        # git itself (the buildspec never uses --force).
        Sid      = "OnlyMain"
        Effect   = "Deny"
        Action   = ["codecommit:GitPush"]
        Resource = local.app.codecommit_repo_arn
        Condition = {
          Null            = { "codecommit:References" = "false" }
          StringNotEquals = { "codecommit:References" = "refs/heads/main" }
        }
      },
      {
        Sid      = "NoBranchDeletion"
        Effect   = "Deny"
        Action   = ["codecommit:DeleteBranch"]
        Resource = local.app.codecommit_repo_arn
      },
    ]
  })
}

resource "aws_codebuild_project" "promote" {
  name          = "${var.name}-promote-main"
  description   = "Fast-forward main to the commit that passed UAT (starts the production frontend build)"
  service_role  = aws_iam_role.promote.arn
  build_timeout = 10

  artifacts { type = "CODEPIPELINE" }
  source {
    type      = "CODEPIPELINE"
    buildspec = "${local.buildspec_dir}/promote.yml"
  }
  environment {
    compute_type = "BUILD_GENERAL1_SMALL"
    image        = local.image
    type         = "LINUX_CONTAINER"
    environment_variable {
      name  = "REPO_NAME"
      value = local.app.codecommit_repo_name
    }
  }
  logs_config {
    cloudwatch_logs {
      group_name  = aws_cloudwatch_log_group.codebuild.name
      stream_name = "promote"
    }
  }
}

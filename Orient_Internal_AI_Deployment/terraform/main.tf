# Architecture v2 (docs/architecture-v2.md): Lambdas run OUTSIDE any VPC and reach a PRIVATE Aurora
# cluster through the RDS Data API (IAM-signed HTTPS). No NAT, no Elastic IP, no open DB port.
# Frontend backend (Cognito) = Amplify Gen 2 (frontend/amplify). Interview agent = AgentCore CLI.

data "aws_caller_identity" "current" {}
data "aws_availability_zones" "available" { state = "available" }

locals {
  azs      = slice(data.aws_availability_zones.available.names, 0, 2)
  prefix   = "${var.name}-${var.environment}"
  ai_on    = var.agentcore_runtime_arn != ""
  seed_pwd = var.seed_password != null ? var.seed_password : random_password.seed.result
}

# ---------------------------------------------------------------- generated secrets
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "jwt" {
  length  = 64
  special = false
}

resource "random_password" "webhook" {
  length  = 48
  special = false
}

resource "random_password" "seed" {
  length  = 20
  special = false
}

# ---------------------------------------------------------------- network for Aurora only
# Aurora needs a subnet group. This VPC has no internet gateway, no NAT and no endpoints, and the
# DB security group has no inbound rule at all: the database is reachable only via the Data API.
resource "aws_vpc" "db" {
  cidr_block           = "10.40.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = "${local.prefix}-db-vpc" }
}

resource "aws_subnet" "db" {
  count             = 2
  vpc_id            = aws_vpc.db.id
  cidr_block        = cidrsubnet(aws_vpc.db.cidr_block, 8, count.index)
  availability_zone = local.azs[count.index]
  tags              = { Name = "${local.prefix}-db-${count.index}" }
}

resource "aws_security_group" "db" {
  name_prefix = "${local.prefix}-db-"
  vpc_id      = aws_vpc.db.id
  description = "Aurora: no inbound rules (Data API access only)"
  lifecycle { create_before_destroy = true }
}

# ---------------------------------------------------------------- database credentials (Data API)
resource "aws_secretsmanager_secret" "db" {
  name                    = "${local.prefix}/db-credentials"
  description             = "Aurora master credentials used by the RDS Data API"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "db" {
  secret_id = aws_secretsmanager_secret.db.id
  secret_string = jsonencode({
    username = "ora_admin"
    password = random_password.db.result
  })
}

# ---------------------------------------------------------------- Aurora Serverless v2 (private, Data API on)
resource "aws_db_subnet_group" "main" {
  name       = "${local.prefix}-db"
  subnet_ids = aws_subnet.db[*].id
}

resource "aws_rds_cluster" "main" {
  cluster_identifier        = "${local.prefix}-db"
  engine                    = "aurora-postgresql"
  engine_version            = "16.8"
  database_name             = "ora"
  master_username           = "ora_admin"
  master_password           = random_password.db.result
  db_subnet_group_name      = aws_db_subnet_group.main.name
  vpc_security_group_ids    = [aws_security_group.db.id]
  enable_http_endpoint      = true # RDS Data API
  storage_encrypted         = true
  backup_retention_period   = 7
  deletion_protection       = true
  skip_final_snapshot       = false
  final_snapshot_identifier = "${local.prefix}-db-final"
  copy_tags_to_snapshot     = true
  apply_immediately         = true

  serverlessv2_scaling_configuration {
    min_capacity             = var.db_min_acu
    max_capacity             = var.db_max_acu
    seconds_until_auto_pause = var.db_min_acu == 0 ? 600 : null
  }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier          = "${local.prefix}-db-1"
  cluster_identifier  = aws_rds_cluster.main.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.main.engine
  engine_version      = aws_rds_cluster.main.engine_version
  publicly_accessible = false
}

# ---------------------------------------------------------------- files bucket (private)
resource "aws_s3_bucket" "files" {
  bucket = "${local.prefix}-files-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "files" {
  bucket = aws_s3_bucket.files.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_policy" "files_tls_only" {
  bucket = aws_s3_bucket.files.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.files.arn, "${aws_s3_bucket.files.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

# ---------------------------------------------------------------- Lambda artifact bucket
resource "aws_s3_bucket" "artifacts" {
  bucket = "${local.prefix}-artifacts-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  bucket                  = aws_s3_bucket.artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  bucket = aws_s3_bucket.artifacts.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = var.lambda_package_dir
  output_path = "${path.module}/.build/lambda.zip"
}

resource "aws_s3_object" "lambda" {
  bucket      = aws_s3_bucket.artifacts.id
  key         = "lambda/${data.archive_file.lambda.output_md5}.zip"
  source      = data.archive_file.lambda.output_path
  source_hash = data.archive_file.lambda.output_md5
}

# ---------------------------------------------------------------- Lambda (no VPC)
resource "aws_iam_role" "lambda" {
  name = "${local.prefix}-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda_logs" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda" {
  name = "app-access"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = concat(
      [
        {
          Sid      = "FilesBucket"
          Effect   = "Allow"
          Action   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
          Resource = "${aws_s3_bucket.files.arn}/*"
        },
        {
          # Data API: the only path to the database, scoped to this one cluster.
          Sid    = "DatabaseViaDataApi"
          Effect = "Allow"
          Action = [
            "rds-data:ExecuteStatement",
            "rds-data:BatchExecuteStatement",
            "rds-data:BeginTransaction",
            "rds-data:CommitTransaction",
            "rds-data:RollbackTransaction"
          ]
          Resource = aws_rds_cluster.main.arn
        },
        {
          Sid      = "DatabaseCredentials"
          Effect   = "Allow"
          Action   = ["secretsmanager:GetSecretValue"]
          Resource = aws_secretsmanager_secret.db.arn
        },
        {
          Sid      = "SendEmail"
          Effect   = "Allow"
          Action   = ["ses:SendEmail", "ses:SendRawEmail"]
          Resource = "*"
        }
      ],
      local.ai_on ? [{
        Sid    = "InvokeInterviewAgent"
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeAgentRuntime",
          "bedrock-agentcore:InvokeAgentRuntimeWithWebSocketStream"
        ]
        Resource = [var.agentcore_runtime_arn, "${var.agentcore_runtime_arn}/*"]
      }] : []
    )
  })
}

locals {
  # Requires the backend to use the Aurora Data API SQLAlchemy dialect (see README, "Data API prerequisite").
  database_url = "postgresql+auroradataapi://:@/ora?aurora_cluster_arn=${urlencode(aws_rds_cluster.main.arn)}&secret_arn=${urlencode(aws_secretsmanager_secret.db.arn)}"

  common_env = merge(
    {
      ORA_ENVIRONMENT          = "staging"
      ORA_DATABASE_URL         = local.database_url
      ORA_JWT_SECRET           = random_password.jwt.result
      ORA_CORS_ALLOWED_ORIGINS = var.app_base_url != "" ? jsonencode([var.app_base_url]) : "[\"https://pending.invalid\"]"
      ORA_S3_BUCKET            = aws_s3_bucket.files.bucket
      ORA_DB_NULL_POOL         = "true"
    },
    var.app_base_url != "" ? { ORA_APP_BASE_URL = var.app_base_url } : {},
    local.ai_on ? {
      ORA_AI_INTERVIEW_ENABLED          = "true"
      ORA_AI_INTERVIEW_AGENT_MODE       = "agentcore"
      ORA_AI_INTERVIEW_AGENTCORE_ARN    = var.agentcore_runtime_arn
      ORA_AI_INTERVIEW_AGENTCORE_REGION = var.region
      ORA_AI_INTERVIEW_WEBHOOK_SECRET   = random_password.webhook.result
    } : {}
  )
}

resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.prefix}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "ops" {
  name              = "/aws/lambda/${local.prefix}-ops"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "api" {
  function_name    = "${local.prefix}-api"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "app.lambda_handler.handler"
  s3_bucket        = aws_s3_object.lambda.bucket
  s3_key           = aws_s3_object.lambda.key
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 1024
  timeout          = 29

  environment { variables = local.common_env }
  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.api.name
  }
  depends_on = [aws_iam_role_policy_attachment.lambda_logs]
}

# Migrations / seeding only. No URL, no API route: IAM invoke only.
# Invoke with {"action": "migrate" | "seed" | "migrate_and_seed"}.
resource "aws_lambda_function" "ops" {
  function_name    = "${local.prefix}-ops"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "app.ops_handler.handler"
  s3_bucket        = aws_s3_object.lambda.bucket
  s3_key           = aws_s3_object.lambda.key
  source_code_hash = data.archive_file.lambda.output_base64sha256
  memory_size      = 1024
  timeout          = 900

  environment {
    variables = merge(local.common_env, { ORA_SEED_PASSWORD = local.seed_pwd })
  }
  logging_config {
    log_format = "JSON"
    log_group  = aws_cloudwatch_log_group.ops.name
  }
  depends_on = [aws_iam_role_policy_attachment.lambda_logs]
}

# ---------------------------------------------------------------- API Gateway (only entry point)
# No Lambda Function URL exists: the API Lambda can be invoked only by this API (and IAM).
# Add a Cognito JWT authorizer here when login moves to Cognito (phase 2).
resource "aws_cloudwatch_log_group" "apigw" {
  name              = "/aws/apigateway/${local.prefix}-http"
  retention_in_days = var.log_retention_days
}

resource "aws_apigatewayv2_api" "http" {
  name          = "${local.prefix}-http"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
  timeout_milliseconds   = 29000
}

resource "aws_apigatewayv2_route" "proxy" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "ANY /{proxy+}"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    throttling_rate_limit  = var.api_rate_limit
    throttling_burst_limit = var.api_burst_limit
  }
  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.apigw.arn
    # No request bodies, query strings or auth headers are logged (candidate PII).
    format = jsonencode({
      requestId = "$context.requestId"
      ip        = "$context.identity.sourceIp"
      method    = "$context.httpMethod"
      path      = "$context.path"
      status    = "$context.status"
      latencyMs = "$context.responseLatency"
      error     = "$context.error.messageString"
    })
  }
}

resource "aws_lambda_permission" "apigw_invoke" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# ---------------------------------------------------------------- Amplify Hosting shell
# Terraform creates the app + branch and the /api/* rewrite. The Amplify Gen 2 backend (Cognito) is
# deployed into this app/branch by `npx ampx pipeline-deploy`, and the SPA by a zip deployment.
resource "aws_amplify_app" "web" {
  name     = "${local.prefix}-web"
  platform = "WEB"

  custom_rule {
    source = "/api/<*>"
    target = "${trimsuffix(aws_apigatewayv2_api.http.api_endpoint, "/")}/api/<*>"
    status = "200"
  }
  custom_rule {
    source = "</^[^.]+$|\\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp|mp4)$)([^.]+$)/>"
    target = "/index.html"
    status = "200"
  }
}

resource "aws_amplify_branch" "main" {
  app_id      = aws_amplify_app.web.id
  branch_name = "main"
  stage       = "PRODUCTION"
}

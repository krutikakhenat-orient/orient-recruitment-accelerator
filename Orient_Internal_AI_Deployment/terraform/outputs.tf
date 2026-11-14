output "amplify_app_id" { value = aws_amplify_app.web.id }
output "amplify_url" { value = "https://${var.amplify_branch}.${aws_amplify_app.web.default_domain}" }
output "environment" { value = var.environment }
output "api_url" { value = aws_apigatewayv2_api.http.api_endpoint }
output "api_lambda_role_arn" { value = aws_iam_role.lambda.arn }
output "ops_function_name" { value = aws_lambda_function.ops.function_name }
# Read by terraform-pipeline/ (remote state) so the release pipeline targets these exact resources.
output "api_function_name" { value = aws_lambda_function.api.function_name }
output "api_function_arn" { value = aws_lambda_function.api.arn }
output "ops_function_arn" { value = aws_lambda_function.ops.arn }
output "api_alias_name" { value = aws_lambda_alias.api_live.name }
output "artifacts_bucket" { value = aws_s3_bucket.artifacts.bucket }
output "db_cluster_id" { value = aws_rds_cluster.main.cluster_identifier }
output "codecommit_repo_name" { value = local.repo_name }
output "codecommit_repo_arn" { value = local.repo_arn }
output "codecommit_clone_url_http" { value = local.repo_clone_url_http }
output "files_bucket" { value = aws_s3_bucket.files.bucket }
output "db_cluster_arn" { value = aws_rds_cluster.main.arn }
output "db_secret_arn" { value = aws_secretsmanager_secret.db.arn }
output "ai_interview_enabled" { value = local.ai_on }
output "hr_chatbot_enabled" { value = var.hr_chatbot_enabled }
output "hr_kb_id" { value = var.hr_chatbot_enabled ? aws_bedrockagent_knowledge_base.hr[0].id : null }
output "hr_docs_bucket" { value = var.hr_chatbot_enabled ? aws_s3_bucket.hr_docs[0].bucket : null }
# Shared HMAC secret: the agent signs result webhooks with it, the API verifies them.
output "webhook_secret" {
  value     = random_password.webhook.result
  sensitive = true
}
output "seed_password" {
  value     = local.seed_pwd
  sensitive = true
}

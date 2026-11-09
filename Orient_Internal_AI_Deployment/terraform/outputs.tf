output "amplify_app_id" { value = aws_amplify_app.web.id }
output "amplify_url" { value = "https://main.${aws_amplify_app.web.default_domain}" }
output "api_url" { value = aws_apigatewayv2_api.http.api_endpoint }
output "api_lambda_role_arn" { value = aws_iam_role.lambda.arn }
output "ops_function_name" { value = aws_lambda_function.ops.function_name }
output "codecommit_clone_url_http" { value = aws_codecommit_repository.app.clone_url_http }
output "files_bucket" { value = aws_s3_bucket.files.bucket }
output "db_cluster_arn" { value = aws_rds_cluster.main.arn }
output "db_secret_arn" { value = aws_secretsmanager_secret.db.arn }
output "ai_interview_enabled" { value = local.ai_on }
output "seed_password" {
  value     = local.seed_pwd
  sensitive = true
}

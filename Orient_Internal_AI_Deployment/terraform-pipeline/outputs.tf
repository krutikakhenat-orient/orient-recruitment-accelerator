output "pipeline_name" { value = aws_codepipeline.backend.name }
output "pipeline_console_url" {
  value = "https://${var.region}.console.aws.amazon.com/codesuite/codepipeline/pipelines/${aws_codepipeline.backend.name}/view?region=${var.region}"
}
output "approvals_topic_arn" { value = aws_sns_topic.approvals.arn }
output "release_marker_parameter" { value = aws_ssm_parameter.last_release.name }
output "codebuild_log_group" { value = aws_cloudwatch_log_group.codebuild.name }

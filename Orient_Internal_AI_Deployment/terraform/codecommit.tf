# Source repository in AWS CodeCommit (account Orient_Internal_AI). One repository serves every
# environment: production creates and owns it; other environments (UAT) only reference it.
# Tags come from the provider default_tags.
resource "aws_codecommit_repository" "app" {
  count           = var.create_codecommit_repo ? 1 : 0
  repository_name = var.codecommit_repo_name
  description     = "HR Accelerator: backend, frontend (Amplify Gen 2), AgentCore agent and deployment code"
  default_branch  = "main"
}

# Existing production state had the repository without count.
moved {
  from = aws_codecommit_repository.app
  to   = aws_codecommit_repository.app[0]
}

data "aws_codecommit_repository" "app" {
  count           = var.create_codecommit_repo ? 0 : 1
  repository_name = var.codecommit_repo_name
}

locals {
  repo_arn            = var.create_codecommit_repo ? aws_codecommit_repository.app[0].arn : data.aws_codecommit_repository.app[0].arn
  repo_name           = var.codecommit_repo_name
  repo_clone_url_http = var.create_codecommit_repo ? aws_codecommit_repository.app[0].clone_url_http : data.aws_codecommit_repository.app[0].clone_url_http
}

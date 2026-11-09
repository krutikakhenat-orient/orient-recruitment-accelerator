# Source repository in AWS CodeCommit (account Orient_Internal_AI). Used as the source for Amplify Hosting
# and for the AWS-side pipeline. Tags come from the provider default_tags.
resource "aws_codecommit_repository" "app" {
  repository_name = var.codecommit_repo_name
  description     = "HR Accelerator: backend, frontend (Amplify Gen 2), AgentCore agent and deployment code"
  default_branch  = "main"
}

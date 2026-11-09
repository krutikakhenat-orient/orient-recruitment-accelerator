variable "aws_profile" {
  type    = string
  default = "Orient_Internal_AI"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "name" {
  description = "Resource name prefix."
  type        = string
  default     = "ora"
}

variable "lambda_package_dir" {
  description = "Folder produced by scripts\\build-lambda.ps1."
  type        = string
  default     = "../.build/lambda"
}

variable "db_min_acu" {
  description = "0 lets Aurora auto-pause when idle (cheapest; first request after idle is slow)."
  type        = number
  default     = 0
}

variable "db_max_acu" {
  type    = number
  default = 2
}

variable "app_base_url" {
  description = "Public Amplify URL (used for CORS and links). Known after the first apply."
  type        = string
  default     = "https://main.d34zadd4sik8o2.amplifyapp.com"
}

variable "agentcore_runtime_arn" {
  description = "ARN of the AgentCore interview runtime (deployed with the agentcore CLI, scripts/deploy-agent.ps1). Empty turns the AI interview feature off."
  type        = string
  # Set as the default so a plain `terraform apply` keeps the feature on.
  default = "arn:aws:bedrock-agentcore:ap-south-1:917511768830:runtime/InterviewAgent_interview_agent-27ewSV3kTB"
}

variable "seed_password" {
  description = "Password for synthetic seed users (staging only)."
  type        = string
  sensitive   = true
  default     = null
}

variable "api_rate_limit" {
  description = "API Gateway steady-state requests/second (all routes)."
  type        = number
  default     = 50
}

variable "api_burst_limit" {
  type    = number
  default = 100
}

variable "codecommit_repo_name" {
  type    = string
  default = "orient-recruitment-accelerator"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

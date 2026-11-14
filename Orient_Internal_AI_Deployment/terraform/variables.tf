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

variable "create_codecommit_repo" {
  description = "true only for the environment that owns the shared repository (production)."
  type        = bool
  default     = true
}

variable "amplify_branch" {
  description = "Git branch the Amplify app builds: main (production) or develop (UAT)."
  type        = string
  default     = "main"
}

variable "amplify_stage" {
  type    = string
  default = "PRODUCTION"
}

variable "amplify_extra_env" {
  description = "Extra Amplify build environment variables (e.g. ORA_ENVIRONMENT=uat for cost tags)."
  type        = map(string)
  default     = {}
}

variable "codecommit_repo_name" {
  type    = string
  default = "orient-recruitment-accelerator"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

# ---------------------------------------------------------------- HR policy chatbot (ADR-0017)
variable "hr_chatbot_enabled" {
  description = "Create the Bedrock Knowledge Base stack and switch the API to it. false = keyword search only (no chatbot AWS resources)."
  type        = bool
  default     = false
}

variable "hr_chatbot_model_id" {
  description = "Bedrock generation model for answers. gpt-oss-20b runs on demand in ap-south-1 (no cross-region routing)."
  type        = string
  default     = "openai.gpt-oss-20b-1:0"
}

variable "hr_chatbot_embedding_model_id" {
  type    = string
  default = "amazon.titan-embed-text-v2:0"
}

variable "hr_chatbot_min_score" {
  description = "Minimum retrieval score for a passage to be used (Phase 0 trial: relevant 0.73-0.85, unrelated 0.49-0.60)."
  type        = number
  default     = 0.65
}

variable "hr_chatbot_reconcile_cron" {
  description = "When the nightly settle + reconcile job runs (UTC). Default 20:30 UTC = 02:00 IST. Kept to once a day so Aurora can stay paused."
  type        = string
  default     = "cron(30 20 * * ? *)"
}

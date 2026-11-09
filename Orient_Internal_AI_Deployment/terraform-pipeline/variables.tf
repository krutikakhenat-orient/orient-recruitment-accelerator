variable "aws_profile" {
  type    = string
  default = "Orient_Internal_AI"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}

variable "environment" {
  description = "Matches the app stack (resource prefix ora-<environment>)."
  type        = string
  default     = "staging"
}

variable "name" {
  type    = string
  default = "ora"
}

variable "state_bucket" {
  description = "Terraform state bucket shared with the app stack (scripts/bootstrap-backend.ps1)."
  type        = string
  default     = "ora-tfstate-917511768830-ap-south-1"
}

variable "app_state_key" {
  description = "State key of the app stack (terraform/). The pipeline reads its outputs."
  type        = string
  default     = "hr-accelerator/staging/terraform.tfstate"
}

variable "branch" {
  type    = string
  default = "main"
}

variable "approver_emails" {
  description = "Release approvers notified by email. Each address must confirm the SNS subscription once."
  type        = list(string)
  default     = ["sumanpramanik@orientindia.net"]
}

variable "pip_audit_enforce" {
  description = "true: known-vulnerable dependencies fail the build. false: reported on the approval message only."
  type        = bool
  default     = false
}

variable "gitleaks_version" {
  type    = string
  default = "8.30.1"
}

variable "gitleaks_linux_x64_sha256" {
  description = "SHA-256 of gitleaks_<version>_linux_x64.tar.gz from the release's checksums.txt."
  type        = string
  default     = "551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb"
}

variable "log_retention_days" {
  type    = number
  default = 30
}

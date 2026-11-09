terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.22"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.7"
    }
  }

  # Remote state in S3 with native lockfile locking (Terraform >= 1.10, no DynamoDB needed).
  # Bucket/key/region are supplied at init time from scripts\bootstrap-backend.ps1 output:
  #   terraform init -backend-config=backend.hcl
  backend "s3" {}
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null # empty in CI (OIDC credentials)

  default_tags {
    tags = {
      Project     = "orient-recruitment-accelerator"
      Application = "HR Accelerator"
      Environment = var.environment
      Owner       = "sumanpramanik@orientindia.net"
      CostCenter  = "Orient_Internal_AI"
      ManagedBy   = "terraform"
    }
  }
}

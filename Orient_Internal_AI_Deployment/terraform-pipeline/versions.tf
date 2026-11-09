# Backend release pipeline (CodeCommit -> CodePipeline -> CodeBuild).
# Applied LOCALLY only, like the app stack. The pipeline never runs Terraform and cannot change itself.
#
#   terraform init -backend-config=../terraform/backend.hcl -backend-config="key=hr-accelerator/pipeline/terraform.tfstate"
#   terraform apply
terraform {
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.22"
    }
  }

  backend "s3" {}
}

provider "aws" {
  region  = var.region
  profile = var.aws_profile != "" ? var.aws_profile : null

  default_tags {
    tags = {
      Project     = "orient-recruitment-accelerator"
      Application = "HR Accelerator CI/CD"
      Environment = var.environment
      Owner       = "sumanpramanik@orientindia.net"
      CostCenter  = "Orient_Internal_AI"
      ManagedBy   = "terraform"
    }
  }
}

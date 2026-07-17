terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state, backed by the bucket/table created once via
  # infra/terraform/bootstrap. This is required (not just "recommended")
  # because infra-prod.yml runs `terraform apply` on an ephemeral
  # GitHub-hosted runner: without a persisted remote state, every run starts
  # from empty state and tries to re-create resources a previous run already
  # created, failing with "already exists"/"Duplicate" errors from AWS.
  #
  # Bucket/table names aren't secret but are account-specific, so they're
  # supplied via `-backend-config=backend.hcl` (see backend.hcl.example)
  # rather than hard-coded here.
  backend "s3" {}
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "office-manager"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

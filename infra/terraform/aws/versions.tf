terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state is recommended once more than one operator applies this
  # config (e.g. an S3 backend with a DynamoDB lock table). Left as local
  # state for the initial "greenfield" bootstrap to keep Phase 1 as cheap
  # and simple as possible — configure a backend block here before a second
  # environment (e.g. staging) is added.
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

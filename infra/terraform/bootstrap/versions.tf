terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # This module provisions the remote state backend itself, so it can't use
  # that backend (chicken-and-egg) — it deliberately keeps local state. It is
  # applied once, by hand, by whoever bootstraps the account, not by CI.
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "office-manager"
      Environment = "shared"
      ManagedBy   = "terraform"
      Purpose     = "terraform-remote-state"
    }
  }
}

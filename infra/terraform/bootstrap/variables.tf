variable "aws_region" {
  description = "AWS region to create the state bucket/lock table in. Should match infra/terraform/aws's aws_region."
  type        = string
  default     = "us-east-2"
}

variable "state_bucket_name" {
  description = "Globally-unique S3 bucket name to hold Terraform state (e.g. \"office-manager-tfstate-<your-account-id>\")."
  type        = string
}

variable "lock_table_name" {
  description = "DynamoDB table name used for Terraform state locking."
  type        = string
  default     = "office-manager-tfstate-lock"
}

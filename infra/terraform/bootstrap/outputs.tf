output "state_bucket" {
  description = "S3 bucket name holding Terraform state. Use as `bucket` in infra/terraform/aws/backend.hcl."
  value       = aws_s3_bucket.tfstate.bucket
}

output "lock_table" {
  description = "DynamoDB table name for state locking. Use as `dynamodb_table` in infra/terraform/aws/backend.hcl."
  value       = aws_dynamodb_table.tfstate_lock.name
}

output "github_actions_infra_role_arn" {
  description = "Role ARN for infra-prod.yml's `infra` job. Set as the AWS_INFRA_ROLE_ARN repository secret."
  value       = aws_iam_role.github_actions_infra.arn
}

output "github_actions_ecr_push_role_arn" {
  description = "Role ARN for infra-prod.yml's `build-and-push` job. Set as the AWS_ECR_PUSH_ROLE_ARN repository secret."
  value       = aws_iam_role.github_actions_ecr_push.arn
}

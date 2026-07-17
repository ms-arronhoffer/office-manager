output "state_bucket" {
  description = "S3 bucket name holding Terraform state. Use as `bucket` in infra/terraform/aws/backend.hcl."
  value       = aws_s3_bucket.tfstate.bucket
}

output "lock_table" {
  description = "DynamoDB table name for state locking. Use as `dynamodb_table` in infra/terraform/aws/backend.hcl."
  value       = aws_dynamodb_table.tfstate_lock.name
}

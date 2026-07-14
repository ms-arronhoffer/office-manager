output "app_instance_id" {
  description = "EC2 instance id for the Phase 1 application host."
  value       = aws_instance.app.id
}

output "app_public_ip" {
  description = "Public IP of the application host. Point your DNS (Route 53 or otherwise) at this until an ALB is introduced in Phase 2."
  value       = aws_instance.app.public_ip
}

output "db_endpoint" {
  description = "RDS Postgres connection endpoint (host:port)."
  value       = aws_db_instance.this.endpoint
}

output "db_address" {
  description = "RDS Postgres host name, for POSTGRES_HOST."
  value       = aws_db_instance.this.address
}

output "uploads_bucket" {
  description = "S3 bucket name for STORAGE_BACKEND=s3 / S3_UPLOAD_BUCKET."
  value       = aws_s3_bucket.uploads.bucket
}

output "backups_bucket" {
  description = "S3 bucket name for the nightly pg_dump + volume backup script."
  value       = aws_s3_bucket.backups.bucket
}

output "app_secrets_arn" {
  description = "ARN of the Secrets Manager secret holding app credentials."
  value       = aws_secretsmanager_secret.app.arn
}

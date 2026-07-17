# One-time bootstrap: the S3 bucket + DynamoDB table that
# infra/terraform/aws's remote state backend points at (see its
# `backend "s3"` block in versions.tf and backend.hcl.example). Run this
# manually, once, per AWS account before the first `terraform init` in
# infra/terraform/aws that references the resulting bucket/table names.

resource "aws_s3_bucket" "tfstate" {
  bucket = var.state_bucket_name

  # Guard against `terraform destroy` accidentally deleting all recorded
  # deployment history for every environment.
  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket                  = aws_s3_bucket.tfstate.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_dynamodb_table" "tfstate_lock" {
  name         = var.lock_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  lifecycle {
    prevent_destroy = true
  }
}

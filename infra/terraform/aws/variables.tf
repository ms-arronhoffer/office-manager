# ── General ──────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-2"
}

variable "environment" {
  description = "Deployment environment name, used for tagging and naming."
  type        = string
  default     = "prod"
}

variable "project_name" {
  description = "Short name used as a prefix for resource names."
  type        = string
  default     = "office-manager"
}

# ── Networking ──────────────────────────────────────────────────────────────
# Phase 1 intentionally reuses the account's default VPC/subnets to avoid the
# cost and complexity of NAT gateways, extra ENIs, etc. Move to a dedicated
# VPC with private subnets + NAT once the Phase 2 multi-instance/ECS
# architecture is adopted.

variable "vpc_id" {
  description = "VPC to deploy into. Leave empty to use the account's default VPC."
  type        = string
  default     = ""
}

variable "subnet_ids" {
  description = "Subnet ids to use for the RDS subnet group. Leave empty to use the default VPC's subnets."
  type        = list(string)
  default     = []
}

variable "ssh_allowed_cidrs" {
  description = "CIDR blocks allowed to reach the app EC2 instance over SSH (port 22). Restrict this to your office/VPN IP range."
  type        = list(string)
  default     = ["74.133.78.157/32"]
}

variable "npm_admin_allowed_cidrs" {
  description = "CIDR blocks allowed to reach the Nginx Proxy Manager admin UI (port 81). Restrict this to your office/VPN IP range; leave empty to keep the admin UI closed and reach it via an SSH tunnel/SSM port-forward instead."
  type        = list(string)
  default     = ["74.133.78.157/32"]
}

variable "app_allowed_cidrs" {
  description = "CIDR blocks allowed to reach the app over HTTP/HTTPS (80/443). Defaults to the whole internet since this is a public SaaS app."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# ── Compute (EC2) ─────────────────────────────────────────────────────────────

variable "app_instance_type" {
  description = "EC2 instance type for the single Phase 1 application host. t4g (Graviton/ARM) is ~20% cheaper than the x86 t3 equivalent."
  type        = string
  default     = "t4g.small"
}

variable "app_root_volume_gb" {
  description = "Root EBS volume size (GB) for the application EC2 instance."
  type        = number
  default     = 30
}

variable "key_pair_name" {
  description = "Name of an existing EC2 key pair for SSH access. Leave empty to disable SSH key access (recommended if using SSM Session Manager instead)."
  type        = string
  default     = "Prod Office Manager"
}

variable "app_eip_allocation_id" {
  description = "Allocation id of an existing Elastic IP to attach to the application EC2 instance, giving prod a stable public address that survives instance replacement. Leave empty to keep the ephemeral auto-assigned public IP."
  type        = string
  default     = "eipalloc-04448fb4ab8eeae33"
}

# ── Database (RDS) ────────────────────────────────────────────────────────────

variable "db_instance_class" {
  description = "RDS instance class. db.t4g.micro is the cheapest viable size for 5-20 tenant orgs; scale to db.t4g.medium/large as traffic grows."
  type        = string
  default     = "db.t4g.micro"
}

variable "db_engine_version" {
  description = "PostgreSQL major version, matching docker-compose's postgres:16. A partial version (e.g. \"16\") is resolved to the latest available minor version at apply time via the aws_rds_engine_version data source, avoiding InvalidParameterCombination errors when AWS retires older minor versions."
  type        = string
  default     = "18"
}

variable "db_allocated_storage_gb" {
  description = "Initial RDS storage size (GB)."
  type        = number
  default     = 20
}

variable "db_max_allocated_storage_gb" {
  description = "Ceiling for RDS storage autoscaling (GB); avoids needing a manual resize as data grows."
  type        = number
  default     = 100
}

variable "db_multi_az" {
  description = "Whether to run RDS Multi-AZ. Kept false for Phase 1 (cheapest viable); set true once uptime SLAs matter (Phase 2)."
  type        = bool
  default     = false
}

variable "db_name" {
  description = "Application database name."
  type        = string
  default     = "office_manager"
}

variable "db_username" {
  description = "Master username for RDS."
  type        = string
  default     = "office_admin"
}

variable "db_backup_retention_days" {
  description = "Automated RDS backup retention window, in days."
  type        = number
  default     = 7
}

# ── Secrets ───────────────────────────────────────────────────────────────────
# All sensitive values are supplied at apply time (e.g. via a `terraform.tfvars`
# that is never committed, or `TF_VAR_*` environment variables sourced from CI
# secrets) and stored in AWS Secrets Manager, never written into a resource
# name/tag or plain application config.

variable "db_password" {
  description = "Master password for RDS. Provide via TF_VAR_db_password or a gitignored tfvars file."
  type        = string
  sensitive   = true

  validation {
    # RDS rejects control characters. A trailing newline (e.g. picked up when
    # a secret is stored/exported from a file) is auto-stripped by the
    # trimspace() calls at the point of use (rds.tf, secrets.tf), so it's
    # trimmed here too before checking — this validation only needs to catch
    # *embedded* control characters, which trimspace() can't fix and would
    # otherwise surface as an opaque AWS API error at apply time.
    condition     = can(regex("^[^\\x00-\\x1f\\x7f]*$", trimspace(var.db_password)))
    error_message = "db_password must not contain control characters (check the secret for stray characters, e.g. an embedded newline)."
  }
}

variable "jwt_secret" {
  description = "Application JWT signing secret."
  type        = string
  sensitive   = true
}

variable "default_admin_password" {
  description = "Initial platform admin password, seeded on first boot."
  type        = string
  sensitive   = true
}

variable "stripe_secret_key" {
  description = "Stripe secret API key (optional; billing degrades gracefully if empty)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "gemini_api_key" {
  description = "Google Gemini API key (optional; AI features degrade gracefully if empty)."
  type        = string
  sensitive   = true
  default     = ""
}

variable "sentry_dsn" {
  description = "Sentry DSN for error tracking (optional)."
  type        = string
  sensitive   = true
  default     = ""
}

# ── GitHub Actions self-hosted runner bootstrap ───────────────────────────────
# The `prod` deploy workflow expects a self-hosted runner labeled "aws-prod"
# to exist and be online. Rather than requiring a human to SSH in and run
# `config.sh` by hand, the EC2 instance registers itself as a runner on boot
# using a short-lived registration token it fetches from the GitHub API with
# the PAT below. The PAT only needs the `repo` (classic) or
# "Administration: write" (fine-grained) scope on this repository and should
# be rotated periodically; it is only ever used at boot time to mint the
# actual (1-hour) runner registration token, never stored on disk afterwards.

variable "github_repo" {
  description = "GitHub \"owner/repo\" this runner registers against."
  type        = string
  default     = "ms-arronhoffer/office-manager"
}

variable "github_runner_pat" {
  description = "GitHub PAT used once at boot to fetch a runner registration token. Provide via TF_VAR_github_runner_pat."
  type        = string
  sensitive   = true
  default     = ""
}

variable "github_runner_labels" {
  description = "Comma-separated labels applied to the self-hosted runner registered on the EC2 instance."
  type        = string
  default     = "self-hosted,aws-prod"
}

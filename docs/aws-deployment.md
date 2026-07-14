# AWS Deployment (Phase 1) — Cost-Effective Launch on us-east-2

This document describes the Phase 1 AWS architecture for Portfolio Desk,
sized for **5 tenant organizations at launch, scaling to ~20 within 6–12
months**, in **us-east-2**, with **no data-residency/compliance
constraints**. It intentionally optimizes for the lowest viable cost first
("cheapest viable, scale later") rather than day-one high availability.

`main` remains the development branch and keeps deploying to the existing
VPS/Portainer host via `.github/workflows/deploy.yml` (unchanged). A new
`prod` branch is the AWS deployment target — merge/promote to `prod` to ship
to AWS.

## Architecture

```
                          Route 53 / your domain
                                   │
                                   ▼
                    ┌──────────────────────────────┐
                    │   EC2 t4g.small (Graviton)    │
                    │  ── docker compose ──         │
                    │  frontend (nginx) ─┐          │
                    │  admin-frontend ───┼─▶ backend│
                    │  landing ──────────┘  (uvicorn)│
                    └───────────────┬──────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼                               ▼
         RDS Postgres 16                    S3 (uploads bucket)
         db.t4g.micro, single-AZ            STORAGE_BACKEND=s3
                                    S3 (backups bucket, pg_dump + tar)
```

- **Compute**: a single EC2 `t4g.small` (ARM/Graviton, ~20% cheaper than the
  x86 `t3` equivalent) runs the same `docker compose` stack as today, minus
  the `db` container.
- **Database**: Postgres moves off the EC2 host onto RDS
  (`db.t4g.micro`, single-AZ, gp3 storage with autoscaling up to 100 GB).
  `POSTGRES_HOST`/`POSTGRES_PORT` are already externalized in
  `backend/app/config.py`, so this required no backend code changes.
- **File storage**: uploaded attachments move from the local `uploads` Docker
  volume to S3 via a new pluggable storage backend
  (`backend/app/utils/file_storage.py`, `STORAGE_BACKEND=s3`). This removes
  the single biggest blocker to running more than one backend
  instance/AZ in a later phase.
- **Secrets**: DB password, JWT secret, Stripe/Gemini keys, etc. live in a
  single AWS Secrets Manager secret (`infra/terraform/aws/secrets.tf`); the
  EC2 instance role has read-only access to it.
- **Backups**: the existing nightly `pg_dump` + `uploads` tar script
  (`docs/backup-setup.md`) continues to run from the EC2 host into the new
  Terraform-managed `*-backups` S3 bucket; RDS automated snapshots
  (7-day retention) provide a second, independent recovery point.
- **TLS/DNS**: for Phase 1, terminate TLS with Nginx + Let's Encrypt (or a
  CloudFront distribution once static assets move off nginx in Phase 2) and
  point Route 53 at the EC2 instance's Elastic IP.

## Why this is the cheapest viable setup

- Single small EC2 host instead of ECS/Fargate — no per-task overhead while
  tenant count is 5–20.
- RDS single-AZ `db.t4g.micro` instead of Multi-AZ — acceptable downtime risk
  at this scale; Multi-AZ is a single Terraform flag away when it isn't
  (`db_multi_az` in `variables.tf`).
- Graviton (`t4g`) instance families throughout for ~20% savings over `t3`/`m5`.
- No NAT gateway or private-subnet cost: Phase 1 deploys into the account's
  existing default VPC (see `infra/terraform/aws/network.tf`).
- S3 is pay-per-GB with no idle cost, versus provisioning EBS/EFS capacity
  up front.

## Growth path (Phase 2, not yet provisioned)

When tenant count or traffic outgrows a single EC2 host:
1. Move the backend to ECS Fargate (2+ tasks) behind an ALB — safe today
   because `app/tasks/scheduler.py` already guards every cron job with a
   Postgres advisory lock, so multiple replicas cannot double-run a job.
2. Flip `db_multi_az = true` and consider a read replica for reporting/AI
   "data query" workloads.
3. Move the three SPAs (`frontend`, `admin-frontend`, `landing`) to
   CloudFront + S3 static hosting instead of nginx containers.
4. Add CloudWatch alarms on ALB 5xx rate, RDS CPU/connections, and ECS task
   health; centralize container logs to CloudWatch Logs.

## Terraform

Infrastructure-as-code lives in `infra/terraform/aws/`:

| File | Purpose |
| --- | --- |
| `versions.tf` | Provider/version pins, default tags |
| `variables.tf` | All configurable inputs (region, instance sizes, secrets) |
| `network.tf` | Default-VPC/subnet lookup, ARM AMI lookup |
| `ec2.tf` | App instance, security group, IAM role/instance profile |
| `rds.tf` | RDS Postgres instance, subnet group, security group |
| `s3.tf` | Uploads bucket + backups bucket (versioned, encrypted, lifecycle rules) |
| `secrets.tf` | Single Secrets Manager secret with all app credentials |
| `templates/user_data.sh.tpl` | EC2 boot script: installs Docker, registers the box as a GitHub Actions self-hosted runner |
| `outputs.tf` | RDS endpoint, S3 bucket names, instance id/IP, secret ARN |

### Bootstrapping

```bash
cd infra/terraform/aws
cp terraform.tfvars.example terraform.tfvars   # fill in non-secret values
# Provide secrets via environment variables so they are never written to disk:
export TF_VAR_db_password=...
export TF_VAR_jwt_secret=...
export TF_VAR_default_admin_password=...
export TF_VAR_github_runner_pat=...            # GitHub PAT, repo scope, used once at boot
terraform init
terraform plan
terraform apply
```

State is local for this initial "greenfield" bootstrap to keep Phase 1
simple — configure an S3 + DynamoDB remote backend in `versions.tf` before a
second person/environment needs to run `terraform apply`.

## CI/CD (GitHub Actions)

Two new workflows target the `prod` branch; `main`'s existing
`deploy.yml` (VPS/Portainer) is untouched:

- **`.github/workflows/infra-prod.yml`** — runs `terraform plan`/`apply` on a
  GitHub-hosted runner (it can't run on the self-hosted "aws-prod" runner
  because that runner *is* the EC2 instance this workflow may be creating).
  Triggered on changes under `infra/terraform/aws/**` pushed to `prod`, or
  manually via `workflow_dispatch`.
- **`.github/workflows/deploy-prod.yml`** — builds the four application
  images and runs `docker compose -f docker-compose.prod.yml up -d` on the
  self-hosted runner registered on the EC2 instance (label `aws-prod`),
  mirroring `deploy.yml`'s pattern but pointing at RDS/S3 instead of local
  containers/volumes.

### Required repository secrets

AWS credentials (for `infra-prod.yml`):
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `TF_VAR_DB_PASSWORD`, `TF_VAR_JWT_SECRET`, `TF_VAR_DEFAULT_ADMIN_PASSWORD`
- `TF_VAR_STRIPE_SECRET_KEY`, `TF_VAR_GEMINI_API_KEY`, `TF_VAR_SENTRY_DSN` (optional)
- `RUNNER_REGISTRATION_PAT` — GitHub PAT (repo scope) used by the EC2
  user-data script to mint a short-lived runner registration token

App deploy (for `deploy-prod.yml`), matching the Terraform outputs:
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- `RDS_HOST` (= `terraform output db_address`), `RDS_PORT` (usually `5432`)
- `JWT_SECRET`, `DEFAULT_ADMIN_EMAIL`, `DEFAULT_ADMIN_PASSWORD`
- `S3_UPLOAD_BUCKET` (= `terraform output uploads_bucket`), `S3_UPLOAD_PREFIX`, `AWS_REGION`
- `FRONTEND_URL`, `ADMIN_FRONTEND_URL`, `APP_PORT`, `ADMIN_PORT`, `LANDING_PORT`
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SMTP_*`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `SENTRY_DSN` (optional/as applicable)

## Application code changes

`backend/app/utils/file_storage.py` adds a `STORAGE_BACKEND` switch
(`local` default, `s3` for AWS) used by every place the app previously wrote
directly to `UPLOAD_DIR`:

- `app/routers/attachments.py` (generic entity attachments)
- `app/routers/client_portal.py` (client-portal document uploads)
- `app/routers/vendor_portal.py` (vendor invoice / insurance certificate uploads)
- `app/services/document_search_service.py` (RAG/keyword indexing reads)

Local development and the existing `docker-compose.yml` VPS deploy are
unaffected — `STORAGE_BACKEND` defaults to `local`, preserving the previous
on-disk behavior.

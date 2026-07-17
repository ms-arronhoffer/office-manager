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

State is **remote** (S3 + DynamoDB lock table), configured via the partial
`backend "s3" {}` block in `versions.tf`. This is required, not just
recommended: `infra-prod.yml` runs `terraform apply` on an ephemeral
GitHub-hosted runner, so local state would be thrown away after every run
and the next run would try to re-create every resource, failing with
"already exists"/"Duplicate" errors from AWS.

### One-time: bootstrap the state backend

Before the first `terraform init` in `infra/terraform/aws`, create the S3
bucket + DynamoDB lock table it stores state in, using the separate
`infra/terraform/bootstrap` module (this module keeps local state itself —
it's the one piece of infra that has to exist before remote state can):

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply -var="state_bucket_name=office-manager-tfstate-<your-account-id>"
terraform output   # note state_bucket / lock_table for the next step
```

### Bootstrapping `infra/terraform/aws`

```bash
cd infra/terraform/aws
cp terraform.tfvars.example terraform.tfvars   # fill in non-secret values
cp backend.hcl.example backend.hcl             # fill in the bucket/table from the step above
# Provide secrets via environment variables so they are never written to disk:
export TF_VAR_db_password=...
export TF_VAR_jwt_secret=...
export TF_VAR_default_admin_password=...
export TF_VAR_github_runner_pat=...            # GitHub PAT, repo scope, used once at boot
terraform init -backend-config=backend.hcl
terraform plan
terraform apply
```

In CI, the bucket/table names are supplied via the (non-secret) repository
variables `TF_STATE_BUCKET`, `TF_STATE_LOCK_TABLE`, and optionally
`TF_STATE_REGION` (defaults to `us-east-2`) — see
`.github/workflows/infra-prod.yml`. The state file `key` is fixed to
`aws/prod/terraform.tfstate` in both the workflow and
`backend.hcl.example`; keep them in sync if you ever change it (e.g. to add
a second environment).

### Recovering from "already exists" errors after a state-less apply

If `terraform apply` previously ran without a remote backend (e.g. before
this change) and partially succeeded, AWS already has the real resources
but no state file tracks them. Re-running `terraform apply` after
configuring the remote backend above will *not* fix this by itself — import
each pre-existing resource into the new remote state once, then re-run
`terraform plan` to confirm no further changes are proposed:

```bash
cd infra/terraform/aws
terraform init -backend-config=backend.hcl

terraform import aws_iam_role.app office-manager-prod-app
terraform import aws_db_subnet_group.this office-manager-prod
terraform import aws_s3_bucket.uploads office-manager-prod-uploads
terraform import aws_s3_bucket.backups office-manager-prod-backups

# If the secret was previously destroyed, it sits in a "scheduled for
# deletion" state for its recovery window (30 days by default) and *cannot*
# be created or imported until it's restored — you'll otherwise see
# "InvalidRequestException: You can't create this secret because a secret
# with this name is already scheduled for deletion":
aws secretsmanager restore-secret --secret-id office-manager/prod/app-secrets
terraform import aws_secretsmanager_secret.app office-manager/prod/app-secrets

# Security group ids aren't guessable from the name; look them up first:
aws ec2 describe-security-groups \
  --filters Name=group-name,Values=office-manager-prod-app,office-manager-prod-db \
  --query 'SecurityGroups[].{Name:GroupName,Id:GroupId}'
terraform import aws_security_group.app <sg-id-for-office-manager-prod-app>
terraform import aws_security_group.db  <sg-id-for-office-manager-prod-db>

terraform plan   # should show no create/replace for the imported resources
```

If `aws_db_instance.this` also failed with `InvalidParameterValue: The
input isn't valid. Input can't contain control characters`, it's almost
always a `TF_VAR_db_password` secret with a stray embedded/trailing
character (e.g. a newline picked up when the value was copied from a file
or piped in). `rds.tf`/`secrets.tf` already `trimspace()` the password and
`variables.tf` validates it against `^[^\x00-\x1f\x7f]*$` before it reaches
AWS — if you still hit this error, the plan that was applied (`tfplan`) was
generated *before* that validation/secret value was fixed (e.g. from a
stale run or an out-of-date `TF_VAR_DB_PASSWORD`). Re-check the secret
value for control characters and re-run `terraform plan`/`apply` from
scratch so the current value is re-validated rather than re-applying an old
`tfplan` artifact.

## CI/CD (GitHub Actions)

Two new workflows target the `prod` branch; `main`'s existing
`deploy.yml` (VPS/Portainer) is untouched:

- **`.github/workflows/infra-prod.yml`** — runs `terraform plan`/`apply` on a
  GitHub-hosted runner (it can't run on the self-hosted "aws-prod" runner
  because that runner *is* the EC2 instance this workflow may be creating).
  Triggered on changes under `infra/terraform/aws/**` pushed to `prod` (runs
  `plan` + `apply`, which creates any new resources and updates any changed
  ones), or manually via `workflow_dispatch` with an `action` input:
  - `plan` — show proposed changes only, no apply.
  - `apply` / `update` — plan and apply; provisions new resources and
    updates any resources whose configuration has drifted (these two
    options behave identically since Terraform apply is always
    create-or-update).
  - `destroy` — tears down every resource managed by this state so the
    footprint can be rebuilt from scratch.
- **`.github/workflows/deploy-prod.yml`** — builds the four application
  images and runs `docker compose -f docker-compose.prod.yml up -d` on the
  self-hosted runner registered on the EC2 instance (label `aws-prod`),
  mirroring `deploy.yml`'s pattern but pointing at RDS/S3 instead of local
  containers/volumes.

### Troubleshooting: `permission denied ... /var/run/docker.sock`

If a build step fails with `permission denied while trying to connect to the
Docker daemon socket at unix:///var/run/docker.sock`, the self-hosted runner's
user isn't effectively in the `docker` group. This typically happens when the
user was added to the group *after* the runner service started (group changes
don't apply to already-running processes). Both deploy workflows now include an
`Ensure Docker daemon access` preflight step that self-heals this best-effort.
To fix it permanently on the host, add the runner user to the `docker` group and
restart the runner service so it picks up the new group:

```bash
sudo usermod -aG docker <runner-user>
sudo systemctl restart 'actions.runner.*'
```

### Required repository secrets

AWS credentials (for `infra-prod.yml`):
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
- `TF_VAR_DB_PASSWORD`, `TF_VAR_JWT_SECRET`, `TF_VAR_DEFAULT_ADMIN_PASSWORD`
- `TF_VAR_STRIPE_SECRET_KEY`, `TF_VAR_GEMINI_API_KEY`, `TF_VAR_SENTRY_DSN` (optional)
- `RUNNER_REGISTRATION_PAT` — GitHub PAT (repo scope) used by the EC2
  user-data script to mint a short-lived runner registration token

Repository *variables* (not secrets — bucket/table names aren't sensitive),
for the remote state backend created via `infra/terraform/bootstrap`:
- `TF_STATE_BUCKET` — S3 bucket name from `terraform output state_bucket`
- `TF_STATE_LOCK_TABLE` — DynamoDB table name from `terraform output lock_table`
- `TF_STATE_REGION` (optional) — region the state bucket/table live in;
  defaults to `us-east-2` if unset

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

# Portfolio Desk - S3 Backup and Restore Verification

This guide covers daily PostgreSQL backups, uploaded-file evidence, 35-day S3 retention, and restore verification. AWS production also keeps 14 days of RDS automated backups for point-in-time recovery.

## Recovery Objectives

- **Target RPO:** 24 hours or less. Nightly `pg_dump` backups meet this target when the backup job succeeds. RDS automated backups usually provide a finer recovery point within their 14-day window.
- **Phase 1 target RTO:** 4 hours or less for database restore, application redeploy, uploads validation, DNS/TLS confirmation, and smoke testing. This is an operational target, not an HA guarantee. Single-AZ RDS and one EC2 host can extend recovery when AWS replacement capacity or an operator is unavailable.
- **Phase 2 trigger:** move to Multi-AZ RDS and redundant compute when contractual availability requires a shorter or assured RTO.

---

## What Gets Backed Up

Two files are uploaded to S3 on each run:

---

### 1. Database — `db/db-YYYY-MM-DD.sql.gz`

A compressed SQL dump of the entire PostgreSQL database produced by `pg_dump`. This is the authoritative backup of all application data.

**Contains:**
- All offices, leases, managers, vendors, and users
- Lease notes, attachments metadata, and activity logs
- HVAC records (heat pumps, PM tasks, PM log, issues, contracts, backflows)
- Maintenance tickets and transitions
- Application settings and user preferences

**Format:** Plain SQL wrapped in gzip. Can be restored to any PostgreSQL instance.

**Why `pg_dump` and not the raw data directory?**
Copying the raw `pgdata` folder while PostgreSQL is running can produce a corrupt, unrestorable backup because Postgres may have in-progress writes. `pg_dump` performs a consistent snapshot that is safe to take on a live database.

---

### 2. Uploaded Files

AWS production writes uploads directly to the versioned uploads bucket. Each backup run stores `uploads-manifests/uploads-manifest-YYYY-MM-DD.json` in the backups bucket. The manifest records the source bucket and object metadata so a drill can sample-check object availability without downloading customer content.

Legacy local deployments still create `volumes/volumes-YYYY-MM-DD.tar.gz` from the `uploads` Docker volume.

**Contains:**
- Lease attachments (PDFs, Word documents, images, etc.)
- Any other files uploaded through the application

**Format:** JSON manifest for AWS production, or a gzipped tar archive with internal path `/data/uploads/` for legacy local storage.

---

> **What is NOT backed up:** Application source code and Docker images are not backed up — these can be rebuilt from your Windows source files at any time. The `pgdata` volume (raw Postgres files) is also excluded in favor of the `pg_dump` approach above.

---

## Prerequisites

- Ubuntu server with Docker and Docker Compose already running
- An AWS account with access to create S3 buckets and IAM users
- `sudo` access on the server

---

## Step 1 — Create the S3 Bucket

1. Log into the [AWS Console](https://console.aws.amazon.com) and go to **S3**.
2. Click **Create bucket**.
3. Choose a name (e.g. `mycompany-office-manager-backups`) and a region close to your server.
4. Leave **Block all public access** enabled (default).
5. Enable **Versioning**. The Terraform-managed AWS production bucket enables it automatically.
6. Click **Create bucket**.

Note down the bucket name — you will need it in Step 3.

---

## Step 2 — Create an IAM User with S3 Access

This creates a dedicated AWS user with only the permissions the backup script needs.

1. Go to **IAM → Users → Create user**.
2. Name it something like `office-manager-backup`.
3. Select **Attach policies directly**, then click **Create policy**.
4. Switch to the **JSON** tab and paste the following, replacing `YOUR-BUCKET-NAME` with your bucket name:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME/*"
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::YOUR-BUCKET-NAME"
    }
  ]
}
```

5. Name the policy (e.g. `OfficeManagerBackupPolicy`) and click **Create policy**.
6. Back on the user creation screen, search for and attach the policy you just created.
7. Click **Create user**.
8. Open the new user, go to **Security credentials → Create access key**.
9. Choose **Other** as the use case, click through, and download or copy the **Access Key ID** and **Secret Access Key**.

> These credentials are only shown once. Store them securely.

---

## Step 3 — Install AWS CLI on the Server

SSH into `ubuntu-server-2` and run:

```bash
sudo apt-get update
sudo apt-get install -y awscli
```

Verify the installation:

```bash
aws --version
```

You should see output like `aws-cli/1.x.x Python/3.x.x Linux/...`.

---

## Step 4 — Upload the Backup Files

Using MobaXTerm, upload the following two files from your Windows machine to `~/office-manager/` on the server:

| Local path (Windows) | Server destination |
|---|---|
| `...\office-manager\backup.sh` | `~/office-manager/backup.sh` |
| `...\office-manager\.backup.env.example` | `~/office-manager/.backup.env.example` |

---

## Step 5 — Configure Credentials on the Server

SSH into the server and run:

```bash
cp ~/office-manager/.backup.env.example ~/office-manager/.backup.env
nano ~/office-manager/.backup.env
```

Fill in your values:

```bash
# S3 bucket name — no s3:// prefix. Can include a path prefix:
#   mybucket
#   mybucket/office-manager/backups
S3_BUCKET=your-bucket-name

# AWS production uses the EC2 instance profile. Do not store static keys here.
AWS_DEFAULT_REGION=us-east-2
RETENTION_DAYS=35

# Must match your docker-compose .env values (defaults shown)
POSTGRES_USER=office_admin
POSTGRES_DB=office_manager
POSTGRES_HOST=your-rds-endpoint
POSTGRES_PORT=5432
AWS_SECRET_ID=office-manager/prod/app-secrets
S3_UPLOAD_BUCKET=office-manager-prod-uploads
S3_UPLOAD_PREFIX=uploads
```

Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

Lock the file so only your user can read it:

```bash
chmod 600 ~/office-manager/.backup.env
```

---

## Step 6 — Make the Script Executable

```bash
chmod +x ~/office-manager/backup.sh
```

---

## Step 7 — Test the Backup

Run the script manually and watch the output:

```bash
~/office-manager/backup.sh
```

Expected output:

```
[2026-04-27 02:00:01] Backing up database...
[2026-04-27 02:00:04]   Done: 1.2M
[2026-04-27 02:00:04] Building S3 uploads manifest...
[2026-04-27 02:00:06]   Manifested 125 objects.
[2026-04-27 02:00:06] Uploading to s3://your-bucket-name...
[2026-04-27 02:00:09]   Upload complete.
[2026-04-27 02:00:09] Pruning backups older than 35 days...
[2026-04-27 02:00:09] Backup finished successfully.
```

Confirm the files appeared in your S3 bucket:

```bash
aws s3 ls s3://your-bucket-name/db/
aws s3 ls s3://your-bucket-name/volumes/
```

---

## Step 8 — Schedule Daily Backups with Cron

Open the crontab editor:

```bash
crontab -e
```

If prompted to choose an editor, select `nano` (option 1).

Add this line at the bottom of the file:

```
0 2 * * * /home/arron/office-manager/backup.sh >> /var/log/office-manager-backup.log 2>&1
```

This runs the backup every day at **2:00am**. Save and exit (`Ctrl+O`, `Enter`, `Ctrl+X`).

Verify the cron job was saved:

```bash
crontab -l
```

Create the log file with correct permissions so cron can write to it:

```bash
sudo touch /var/log/office-manager-backup.log
sudo chown arron:arron /var/log/office-manager-backup.log
```

---

## Step 9 — Verify the Next Morning

After the first scheduled run, check the log:

```bash
cat /var/log/office-manager-backup.log
```

And confirm the files are in S3:

```bash
aws s3 ls s3://your-bucket-name/db/
aws s3 ls s3://your-bucket-name/volumes/
```

---

## Restoring from Backup

### Preferred verification drill

Run **AWS Restore Verification Drill** from GitHub Actions. The `recovery-drill` GitHub environment must have required reviewers and the `AWS_RECOVERY_DRILL_ROLE_ARN` environment secret. Supply the Terraform `backups_bucket` output, optionally select a backup key and uploads manifest URI, and type `RESTORE_TO_DISPOSABLE_CONTAINER_ONLY`.

The workflow runs `scripts/verify-backup-restore.sh` on the `docker-build` runner. The script refuses external database targets, creates an unexposed disposable PostgreSQL container, restores the selected dump, checks `alembic_version`, verifies the `organizations`, `users`, `offices`, and `leases` tables, records row counts, optionally checks up to 20 uploads from a manifest, and removes the container on exit.

The bootstrap module creates the read-only recovery role. After applying it:

```bash
cd infra/terraform/bootstrap
terraform apply
terraform output -raw github_actions_recovery_role_arn
```

Store that output as `AWS_RECOVERY_DRILL_ROLE_ARN` in the protected `recovery-drill` GitHub environment. The role can list and read only the production backups and uploads buckets.

> **Before restoring:** The application does not need to be stopped to restore uploaded files, but it is strongly recommended to stop it before restoring the database to avoid data conflicts.

---

### Stop the application (recommended before any restore)

```bash
cd ~/office-manager
docker compose stop backend frontend
```

This keeps the database container running (needed for the restore) but stops the application from accepting new requests while you restore.

---

### Restore the database

**Use this when:** You need to recover lost or corrupted application data — deleted records, bad migrations, accidental changes, etc.

**Step 1 — Download the backup you want to restore:**
```bash
aws s3 cp s3://your-bucket-name/db/db-YYYY-MM-DD.sql.gz /tmp/db-restore.sql.gz
```
Replace `YYYY-MM-DD` with the date of the backup you want (e.g. `2026-04-26`).

**Step 2 — Drop and recreate the database:**
```bash
docker exec -i office-manager-db-1 \
  psql -U office_admin -c "DROP DATABASE office_manager;"

docker exec -i office-manager-db-1 \
  psql -U office_admin -c "CREATE DATABASE office_manager;"
```

**Step 3 — Restore the dump:**
```bash
gunzip -c /tmp/db-restore.sql.gz | docker exec -i office-manager-db-1 \
  psql -U office_admin -d office_manager
```

**Step 4 — Verify the restore:**
```bash
docker exec -i office-manager-db-1 \
  psql -U office_admin -d office_manager -c "\dt"
```
You should see a list of all application tables (offices, leases, users, etc.).

---

### Restore uploaded files

**Use this when:** Attachment files are missing or the `uploads` volume was lost.

**Step 1 — Download the backup:**
```bash
aws s3 cp s3://your-bucket-name/volumes/volumes-YYYY-MM-DD.tar.gz /tmp/volumes-restore.tar.gz
```

**Step 2 — Clear the current uploads volume and restore:**
```bash
docker run --rm \
  -v office-manager_uploads:/data/uploads \
  -v /tmp:/backup \
  alpine sh -c "rm -rf /data/uploads/* && tar xzf /backup/volumes-restore.tar.gz -C /"
```

**Step 3 — Verify the restore:**
```bash
docker run --rm \
  -v office-manager_uploads:/data/uploads \
  alpine ls /data/uploads
```
You should see the restored file structure.

---

### Restart the application

```bash
cd ~/office-manager
docker compose start backend frontend
```

---

### Full disaster recovery (complete data loss)

If the server itself is lost and you are rebuilding from scratch:

1. Set up a new Ubuntu server and install Docker Compose.
2. Copy your source files from Windows to the new server via MobaXTerm.
3. Re-create your `~/office-manager/.env` file with database credentials and JWT secret.
4. Start only the database: `docker compose up -d db`
5. Wait for it to be healthy: `docker compose ps`
6. Restore the database dump using the steps above.
7. Start everything: `docker compose up -d`
8. Restore uploaded files using the steps above.

---

## Retention Policy

Current backup objects expire after **35 days**. Versioning protects against accidental overwrite or deletion, and noncurrent backup versions expire after 7 days. Incomplete multipart uploads are removed after 7 days. RDS automated backups retain 14 days by default, which is the cost-conscious choice within the AWS maximum of 35 days.

Backups are not transitioned to Standard-IA because only five days remain after the 30-day minimum-age point and Standard-IA has a 30-day minimum storage charge. Long-lived noncurrent versions in the uploads bucket transition to Standard-IA after 30 days and expire after 90 days.

Object Lock is intentionally not enabled in Phase 1. Enabling it is irreversible and can change deletion and cost behavior. Terraform does not request bucket replacement. Adopt Object Lock only through a separately reviewed plan that confirms an in-place update and defines governance retention, legal hold, and break-glass procedures.

| Day | Files in S3 |
|-----|-------------|
| Day 1 | Day 1 |
| Day 2 | Day 1, Day 2 |
| Day 3 | Day 1, Day 2, Day 3 |
| Day 35 | Day 1 through Day 35 |
| Day 36 | Day 2 through Day 36 (Day 1 expired) |

## Drill Cadence and Evidence

- Run the disposable restore verification quarterly and after material backup, database, or lifecycle changes.
- Run a full recovery exercise at least annually. Include infrastructure recreation, RDS or dump restore, application deploy, uploads checks, secrets access, DNS/TLS, tenant isolation, and critical smoke tests.
- Record drill date, operator and approver, selected backup key/version, backup creation time, checksum or S3 ETag, migration revision, core table row counts, uploads manifest count and sampled failures, start/end timestamps, measured RPO/RTO, application smoke-test results, exceptions, corrective-action owner, and due date.
- Keep the GitHub run URL, CloudWatch alarm state, relevant log query, and completed evidence record with the recovery ticket. Never attach dumps, credentials, or customer content.

---

## Troubleshooting

**`$'\r': command not found` error**
The script or `.backup.env` file was created on Windows and has Windows line endings (`\r\n`). Fix with:
```bash
sed -i 's/\r//' ~/office-manager/backup.sh
sed -i 's/\r//' ~/office-manager/.backup.env
```

**`S3_BUCKET not set` error**
The `.backup.env` file is missing or in the wrong location. It must be at `~/office-manager/.backup.env`.

**`docker exec` fails with "no such container"**
The database container may have a different name. Check with:
```bash
docker ps --format '{{.Names}}'
```
Update the `COMPOSE_PROJECT` variable in `backup.sh` to match.

**`aws s3 cp` fails with credentials error**
Verify your keys are correct in `.backup.env` and that the IAM policy from Step 2 is attached to the user.

**Cron job doesn't run**
Check that the cron service is running:
```bash
sudo systemctl status cron
```

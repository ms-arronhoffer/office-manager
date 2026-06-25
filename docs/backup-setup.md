# SwiftLease — S3 Backup Setup

This guide sets up automated daily backups of the PostgreSQL database and uploaded files to an AWS S3 bucket. Backups older than 3 days are automatically deleted.

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

### 2. Uploaded Files — `volumes/volumes-YYYY-MM-DD.tar.gz`

A compressed tar archive of the `uploads` Docker volume. This contains all files that users have attached to records (leases, offices, etc.) through the application.

**Contains:**
- Lease attachments (PDFs, Word documents, images, etc.)
- Any other files uploaded through the application

**Format:** Gzipped tar archive. The internal path is `/data/uploads/`.

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
5. Enable **Versioning** — optional but recommended.
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

# AWS credentials from Step 2
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1

# Must match your docker-compose .env values (defaults shown)
POSTGRES_USER=office_admin
POSTGRES_DB=office_manager
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
[2026-04-27 02:00:04] Backing up uploads volume...
[2026-04-27 02:00:06]   Done: 4.5M
[2026-04-27 02:00:06] Uploading to s3://your-bucket-name...
[2026-04-27 02:00:09]   Upload complete.
[2026-04-27 02:00:09] Pruning backups older than 3 days...
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

The backup script automatically deletes files from S3 that are more than **3 days old** on each run. After 3 days of successful backups, you will always have exactly 3 backup sets in S3.

| Day | Files in S3 |
|-----|-------------|
| Day 1 | Day 1 |
| Day 2 | Day 1, Day 2 |
| Day 3 | Day 1, Day 2, Day 3 |
| Day 4 | Day 2, Day 3, Day 4 (Day 1 deleted) |

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

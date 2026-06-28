# SwiftLease Application

A multi-tenant SaaS office and property management platform built with FastAPI, React, and PostgreSQL. Covers the full lifecycle of corporate office portfolios: lease management, HVAC, maintenance, vendors, transitions, billing, and analytics — all in one containerized application.

## Tech Stack

- **Backend**: Python 3.12 / FastAPI / SQLAlchemy (async) / Alembic
- **Frontend**: React 18 / TypeScript / Vite / Cloudscape Design System
- **Admin Frontend**: Separate React SPA for super-admin platform management
- **Database**: PostgreSQL 16
- **Auth**: JWT + Google OAuth + internal accounts (bcrypt) + TOTP two-factor authentication
- **Email**: SMTP via aiosmtplib + APScheduler
- **Reports**: PDF (ReportLab) + CSV export
- **Payments**: Stripe (subscriptions, webhooks, Customer Portal)
- **Rate Limiting**: SlowAPI

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │              Docker Network              │
   Port 3000 ──────┤                                           │
   (configurable)   │  ┌─────────────┐   ┌─────────────────┐  │
                    │  │  frontend   │──▶│    backend      │  │
                    │  │  (nginx)    │   │   (uvicorn)     │  │
                    │  └─────────────┘   └────────┬────────┘  │
                    │                             │           │
   Port 4001 ──────┤  ┌─────────────┐   ┌────────▼────────┐  │
   (configurable)   │  │admin-front  │──▶│       db        │  │
                    │  │  (nginx)    │   │   (postgres)    │  │
                    │  └─────────────┘   └─────────────────┘  │
                    └─────────────────────────────────────────┘
```

- **frontend** (nginx:alpine) — tenant-facing React SPA, proxies `/api/` to the backend
- **admin-frontend** (nginx:alpine) — super-admin management SPA, proxies `/api/` and `/admin/` to the backend
- **backend** (python:3.12-slim) — FastAPI, runs Alembic migrations on startup; serves both `/api/v1/` and `/admin/v1/` routes
- **db** (postgres:16-alpine) — no exposed ports, only reachable within the Docker network

---

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) 20.10+
- [Docker Compose](https://docs.docker.com/compose/install/) v2+
- (Optional) Excel seed data files placed in `backend/seed/data/`

---

## Local Deployment

### 1. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` with your values:

```dotenv
# ── Required ──────────────────────────────────────────
POSTGRES_PASSWORD=your_secure_db_password
JWT_SECRET=your_random_secret_key_min_32_chars

# ── Database (defaults are fine for local dev) ────────
POSTGRES_DB=office_manager
POSTGRES_USER=office_admin

# ── Google OAuth (optional) ───────────────────────────
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=

# ── SMTP Email (optional) ────────────────────────────
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=noreply@officemanager.local

# ── Frontend ──────────────────────────────────────────
FRONTEND_URL=http://localhost:3000
APP_PORT=3000

# ── Default Admin Account ────────────────────────────
DEFAULT_ADMIN_EMAIL=admin@officemanager.local
DEFAULT_ADMIN_PASSWORD=changeme123
```

> **Security**: Generate strong values for `POSTGRES_PASSWORD` and `JWT_SECRET`. Example:
> ```bash
> openssl rand -base64 32
> ```

### 2. Build and Start

```bash
docker compose up --build -d
```

This will:
1. Start PostgreSQL and wait for it to be healthy
2. Start the backend, which creates all tables, creates a default admin user, then starts uvicorn
3. Start the frontend nginx container

The default admin user is created automatically on first startup using `DEFAULT_ADMIN_EMAIL` and `DEFAULT_ADMIN_PASSWORD` from your `.env` file.

### 3. Seed the Database

To populate the application with data, place the Excel source files in `backend/seed/data/` before building:

```
backend/seed/data/
├── Copy of Office Location Master List.xlsx
├── Copy of Lease Expiration Notice Dates.xlsx
├── Copy of Landlord Contacts.xlsx
├── Copy of Closing, Moving, New Offices 2026-2025-2024.xlsx
├── Copy of HQ HVAC System.xlsx
└── HVAC CONTRACT TRACKER.xlsx
```

Then run the seed script:

```bash
docker compose exec backend python -m seed.run_seed
```

To seed only the default organization (creates the default organization, admin
user, email reminder rules, and ticket categories without importing the
spreadsheet data), use the `--bootstrap-only` flag:

```bash
docker compose exec backend python -m seed.run_seed --bootstrap-only
```

### 4. Access the Application

Open `http://localhost:3000` and log in with the default admin credentials:

| Field    | Value                        |
|----------|------------------------------|
| Email    | `admin@officemanager.local`  |
| Password | `changeme123`                |

> **Important**: Change the default admin password immediately after first login.

The default admin (`admin@officemanager.local`) is a platform **super-admin**. To provision an additional dedicated super-admin, run:

```bash
docker compose exec backend python create_superadmin.py \
  --email ops@example.com --password "<strong-password>" --name "Ops Admin"
```

The command creates a new super-admin or, if the email already exists, promotes that account (and resets its password when `--password` is supplied).

The super-admin management interface is available at `http://localhost:4001`. Super-admin accounts require TOTP two-factor authentication — see [docs/MFA_SETUP.md](docs/MFA_SETUP.md).

### 5. Verify

```bash
# Check all containers are running
docker compose ps

# View backend logs
docker compose logs backend -f

# View frontend/nginx logs
docker compose logs frontend -f
```

---

## Local Deployment Behind an External Nginx Reverse Proxy

If you want to run the application behind a host-level nginx reverse proxy (for SSL termination, custom domain, or running alongside other services), follow these additional steps.

### 1. Change the Application Port

In `.env`, pick a non-conflicting internal port:

```dotenv
APP_PORT=3001
FRONTEND_URL=https://officemanager.yourdomain.com
```

### 2. Start the Application

```bash
docker compose up --build -d
```

The app is now listening on `http://localhost:3001` (not publicly exposed yet).

### 3. Install Nginx on the Host

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y nginx

# RHEL/CentOS
sudo dnf install -y nginx
```

### 4. Create the Nginx Site Configuration

Create `/etc/nginx/sites-available/officemanager`:

```nginx
server {
    listen 80;
    server_name officemanager.yourdomain.com;

    # Redirect HTTP to HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name officemanager.yourdomain.com;

    # SSL certificates (use certbot or your own certs)
    ssl_certificate     /etc/letsencrypt/live/officemanager.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/officemanager.yourdomain.com/privkey.pem;

    # SSL settings
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # Proxy everything to the Docker frontend container
    location / {
        proxy_pass http://127.0.0.1:3001;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_cache_bypass $http_upgrade;
        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;

        # Increase buffer sizes for large API responses (reports)
        proxy_buffer_size 16k;
        proxy_buffers 8 16k;
        proxy_busy_buffers_size 32k;
    }

    # Larger body size for file uploads
    client_max_body_size 50M;
}
```

### 5. Enable the Site and Obtain SSL

```bash
# Enable the site
sudo ln -s /etc/nginx/sites-available/officemanager /etc/nginx/sites-enabled/

# Test configuration
sudo nginx -t

# Obtain SSL certificate with certbot
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d officemanager.yourdomain.com

# Reload nginx
sudo systemctl reload nginx
```

### 6. Verify

Open `https://officemanager.yourdomain.com` in your browser. The request flow is:

```
Client ──HTTPS──▶ Host Nginx (443) ──HTTP──▶ Docker Frontend (3001) ──HTTP──▶ Docker Backend (8000)
```

---

## Azure Deployment

Three deployment options are covered below, from most recommended to simplest lift-and-shift.

### Shared Setup (All Options)

```bash
# Set variables — adjust to your needs
RG="officemanager-rg"
LOCATION="eastus"
ACR="officemgracr$(openssl rand -hex 4)"
VNET="officemanager-vnet"
PG_SERVER="officemgr-pg"
PG_USER="pgadmin"
PG_PASS="$(openssl rand -base64 24)"
PG_DB="office_manager"

# Create resource group
az group create --name $RG --location $LOCATION

# Create Azure Container Registry
az acr create --name $ACR --resource-group $RG --sku Basic --admin-enabled true
az acr login --name $ACR

# Build and push images
docker build -t $ACR.azurecr.io/backend:latest ./backend
docker build -t $ACR.azurecr.io/frontend:latest ./frontend
docker push $ACR.azurecr.io/backend:latest
docker push $ACR.azurecr.io/frontend:latest
```

> **Save your credentials**: Record `PG_PASS` and the ACR password (`az acr credential show --name $ACR --query passwords[0].value -o tsv`) somewhere secure.

---

### Option A: Azure Container Apps (Recommended)

Best for production workloads. Auto-scaling, managed infrastructure, lowest ops overhead.

#### 1. Create the Virtual Network

```bash
az network vnet create \
  --name $VNET --resource-group $RG --location $LOCATION \
  --address-prefix 10.0.0.0/16

az network vnet subnet create \
  --name pg-subnet --resource-group $RG --vnet-name $VNET \
  --address-prefix 10.0.1.0/24 \
  --delegations Microsoft.DBforPostgreSQL/flexibleServers

az network vnet subnet create \
  --name aca-subnet --resource-group $RG --vnet-name $VNET \
  --address-prefix 10.0.2.0/23
```

#### 2. Create Private DNS Zone for PostgreSQL

```bash
az network private-dns zone create \
  --name privatelink.postgres.database.azure.com \
  --resource-group $RG

az network private-dns link vnet create \
  --name pg-dns-link --resource-group $RG \
  --zone-name privatelink.postgres.database.azure.com \
  --virtual-network $VNET --registration-enabled false
```

#### 3. Create PostgreSQL Flexible Server (Private)

```bash
az postgres flexible-server create \
  --name $PG_SERVER --resource-group $RG --location $LOCATION \
  --admin-user $PG_USER --admin-password "$PG_PASS" \
  --sku-name Standard_B2ms --tier Burstable \
  --storage-size 32 --version 16 \
  --vnet $VNET --subnet pg-subnet \
  --private-dns-zone privatelink.postgres.database.azure.com \
  --database-name $PG_DB
```

#### 4. Create Container Apps Environment

```bash
ACA_ENV="officemanager-env"

SUBNET_ID=$(az network vnet subnet show \
  --name aca-subnet --resource-group $RG --vnet-name $VNET \
  --query id -o tsv)

az containerapp env create \
  --name $ACA_ENV --resource-group $RG --location $LOCATION \
  --infrastructure-subnet-resource-id $SUBNET_ID
```

#### 5. Deploy Backend

```bash
ACR_PASS=$(az acr credential show --name $ACR --query passwords[0].value -o tsv)
PG_HOST="$PG_SERVER.postgres.database.azure.com"
JWT_SECRET=$(openssl rand -base64 32)

az containerapp create \
  --name backend --resource-group $RG \
  --environment $ACA_ENV \
  --image $ACR.azurecr.io/backend:latest \
  --registry-server $ACR.azurecr.io \
  --registry-username $ACR \
  --registry-password "$ACR_PASS" \
  --target-port 8000 --ingress internal \
  --min-replicas 1 --max-replicas 5 \
  --cpu 0.5 --memory 1.0Gi \
  --env-vars \
    DATABASE_URL="postgresql+asyncpg://$PG_USER:$PG_PASS@$PG_HOST:5432/$PG_DB?sslmode=require" \
    DATABASE_URL_SYNC="postgresql://$PG_USER:$PG_PASS@$PG_HOST:5432/$PG_DB?sslmode=require" \
    JWT_SECRET="$JWT_SECRET" \
    DEFAULT_ADMIN_EMAIL="admin@officemanager.local" \
    DEFAULT_ADMIN_PASSWORD="changeme123" \
    FRONTEND_URL="https://your-frontend-fqdn"
```

#### 6. Deploy Frontend

```bash
BACKEND_FQDN=$(az containerapp show \
  --name backend --resource-group $RG \
  --query properties.configuration.ingress.fqdn -o tsv)

az containerapp create \
  --name frontend --resource-group $RG \
  --environment $ACA_ENV \
  --image $ACR.azurecr.io/frontend:latest \
  --registry-server $ACR.azurecr.io \
  --registry-username $ACR \
  --registry-password "$ACR_PASS" \
  --target-port 80 --ingress external \
  --min-replicas 1 --max-replicas 3 \
  --cpu 0.25 --memory 0.5Gi
```

> **Note**: The frontend nginx container already proxies `/api/` to the backend. For Container Apps, you may need to update `nginx.conf` to proxy to the backend's internal FQDN instead of `backend:8000`. Alternatively, rebuild the frontend image with `BACKEND_URL` pointing to the backend's internal URL.

#### 7. Custom Domain + SSL (Optional)

```bash
DOMAIN="officemanager.yourdomain.com"

az containerapp hostname add \
  --name frontend --resource-group $RG \
  --hostname $DOMAIN

# Free managed certificate
az containerapp hostname bind \
  --name frontend --resource-group $RG \
  --hostname $DOMAIN --validation-method CNAME
```

#### 8. Run Database Seed

```bash
# Execute seed in a one-off revision
az containerapp exec \
  --name backend --resource-group $RG \
  --command "python -m seed.run_seed"
```

---

### Option B: Azure App Service

Best for teams already using App Service. Simpler setup, predictable pricing.

#### 1. Create VNet + PostgreSQL

Follow Steps 1-3 from Option A above, then add an App Service subnet:

```bash
az network vnet subnet create \
  --name appservice-subnet --resource-group $RG --vnet-name $VNET \
  --address-prefix 10.0.4.0/24 \
  --delegations Microsoft.Web/serverFarms
```

#### 2. Create App Service Plan

```bash
az appservice plan create \
  --name officemanager-plan --resource-group $RG \
  --is-linux --sku P2V3
```

#### 3. Deploy Backend

```bash
ACR_PASS=$(az acr credential show --name $ACR --query passwords[0].value -o tsv)
PG_HOST="$PG_SERVER.postgres.database.azure.com"

az webapp create \
  --name officemanager-backend --resource-group $RG \
  --plan officemanager-plan \
  --deployment-container-image-name $ACR.azurecr.io/backend:latest

az webapp config container set \
  --name officemanager-backend --resource-group $RG \
  --container-registry-url https://$ACR.azurecr.io \
  --container-registry-user $ACR \
  --container-registry-password "$ACR_PASS" \
  --container-image-name $ACR.azurecr.io/backend:latest

az webapp config appsettings set \
  --name officemanager-backend --resource-group $RG \
  --settings \
    DATABASE_URL="postgresql+asyncpg://$PG_USER:$PG_PASS@$PG_HOST:5432/$PG_DB?sslmode=require" \
    DATABASE_URL_SYNC="postgresql://$PG_USER:$PG_PASS@$PG_HOST:5432/$PG_DB?sslmode=require" \
    JWT_SECRET="$(openssl rand -base64 32)" \
    DEFAULT_ADMIN_EMAIL="admin@officemanager.local" \
    DEFAULT_ADMIN_PASSWORD="changeme123" \
    WEBSITES_PORT=8000

# Connect backend to VNet so it can reach private PostgreSQL
az webapp vnet-integration add \
  --name officemanager-backend --resource-group $RG \
  --vnet $VNET --subnet appservice-subnet
```

#### 4. Deploy Frontend

```bash
az webapp create \
  --name officemanager-frontend --resource-group $RG \
  --plan officemanager-plan \
  --deployment-container-image-name $ACR.azurecr.io/frontend:latest

az webapp config container set \
  --name officemanager-frontend --resource-group $RG \
  --container-registry-url https://$ACR.azurecr.io \
  --container-registry-user $ACR \
  --container-registry-password "$ACR_PASS" \
  --container-image-name $ACR.azurecr.io/frontend:latest
```

#### 5. Custom Domain + SSL

```bash
az webapp config hostname add \
  --webapp-name officemanager-frontend --resource-group $RG \
  --hostname $DOMAIN

az webapp config ssl create \
  --name officemanager-frontend --resource-group $RG \
  --hostname $DOMAIN
```

---

### Option C: Azure VM with Docker Compose

Best for quick lift-and-shift with minimal changes. Uses the same `docker-compose.yml` workflow.

#### 1. Create the VM

```bash
az vm create \
  --name officemanager-vm --resource-group $RG --location $LOCATION \
  --image Ubuntu2204 --size Standard_D2s_v3 \
  --admin-username azureuser --generate-ssh-keys \
  --public-ip-sku Standard

az vm open-port --name officemanager-vm --resource-group $RG --port 80
az vm open-port --name officemanager-vm --resource-group $RG --port 443
```

#### 2. Install Docker on the VM

```bash
VM_IP=$(az vm show -d --name officemanager-vm --resource-group $RG --query publicIps -o tsv)

ssh azureuser@$VM_IP << 'INSTALL'
sudo apt-get update -y
sudo apt-get install -y docker.io docker-compose-v2
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
INSTALL
```

#### 3. Transfer Files and Start

```bash
# Copy project files to the VM
scp -r ./backend ./frontend ./docker-compose.yml .env azureuser@$VM_IP:~/office-manager/

# SSH in and start
ssh azureuser@$VM_IP
cd ~/office-manager
docker compose up --build -d

# Seed the database
docker compose exec backend python -m seed.run_seed
```

#### 4. Set Up SSL with Certbot

```bash
sudo apt-get install -y certbot python3-certbot-nginx nginx

# Create an nginx site config (see "Local Deployment Behind Nginx" section above)
# Then:
sudo certbot --nginx -d officemanager.yourdomain.com
```

---

### Azure Deployment Comparison

| Criteria              | Container Apps      | App Service         | VM + Compose        |
|-----------------------|---------------------|---------------------|---------------------|
| Auto-scaling          | Yes (0 to N)        | Yes (manual rules)  | No                  |
| Managed SSL           | Free, automatic     | Free managed cert   | Certbot (manual)    |
| Est. Cost (low traffic) | ~$10-30/mo        | ~$80-150/mo         | ~$60-100/mo         |
| Ops Overhead          | Lowest              | Low                 | Highest             |
| Lift-and-shift ease   | Medium              | Medium              | Highest             |
| Private DB support    | Native VNet inject  | VNet Integration    | Same VNet           |

**Recommendation**: Use **Container Apps** for production. Use **VM + Compose** for a quick proof-of-concept that mirrors your local Docker setup exactly.

---

## Configuration Reference

| Variable                 | Required | Default                      | Description                                          |
|--------------------------|----------|------------------------------|------------------------------------------------------|
| `POSTGRES_DB`            | No       | `office_manager`             | PostgreSQL database name                             |
| `POSTGRES_USER`          | No       | `office_admin`               | PostgreSQL username                                  |
| `POSTGRES_PASSWORD`      | **Yes**  | —                            | PostgreSQL password                                  |
| `JWT_SECRET`             | **Yes**  | —                            | Secret key for JWT token signing (min 32 chars)      |
| `GOOGLE_CLIENT_ID`       | No       | —                            | Google OAuth client ID                               |
| `GOOGLE_CLIENT_SECRET`   | No       | —                            | Google OAuth client secret                           |
| `SMTP_HOST`              | No       | —                            | SMTP server hostname                                 |
| `SMTP_PORT`              | No       | `587`                        | SMTP server port                                     |
| `SMTP_USER`              | No       | —                            | SMTP username                                        |
| `SMTP_PASSWORD`          | No       | —                            | SMTP password                                        |
| `SMTP_FROM`              | No       | `noreply@officemanager.local`| From address for outgoing emails                     |
| `FRONTEND_URL`           | No       | `http://localhost:3000`      | Public URL of the frontend (for emails, CORS)        |
| `APP_PORT`               | No       | `3000`                       | Host port the frontend is mapped to                  |
| `ADMIN_PORT`             | No       | `4001`                       | Host port the admin frontend is mapped to            |
| `DEFAULT_ADMIN_EMAIL`    | No       | `admin@officemanager.local`  | Initial admin account email                          |
| `DEFAULT_ADMIN_PASSWORD` | No       | `changeme123`                | Initial admin account password — **change immediately** |
| `STRIPE_SECRET_KEY`      | No       | —                            | Stripe secret key for billing integration            |
| `STRIPE_WEBHOOK_SECRET`  | No       | —                            | Stripe webhook signing secret                        |
| `STRIPE_PRICE_STARTER`   | No       | —                            | Stripe Price ID for the Starter plan                 |
| `STRIPE_PRICE_PRO`       | No       | —                            | Stripe Price ID for the Pro plan                     |
| `STRIPE_PRICE_ENTERPRISE`| No       | —                            | Stripe Price ID for the Enterprise plan              |

---

## Common Operations

```bash
# Stop all services
docker compose down

# Stop and remove volumes (destroys database data)
docker compose down -v

# Rebuild after code changes
docker compose up --build -d

# View logs
docker compose logs -f
docker compose logs backend -f
docker compose logs frontend -f

# Run database migrations manually
docker compose exec backend alembic upgrade head

# Run seed scripts
docker compose exec backend python -m seed.run_seed

# Open a shell in the backend container
docker compose exec backend bash

# Connect to PostgreSQL directly
docker compose exec db psql -U office_admin -d office_manager
```

---

## Application Features

### Core Office Management
- **Dashboard** — summary stats, financial KPI widgets (annual rent, ROU asset, lease liability, CAM over budget), lease expiration chart, upcoming HVAC services, active transitions, real-time push updates via WebSocket
- **Offices** — full CRUD with property filtering by region, type, sector, state; occupancy and capacity tracking
- **Leases** — tracking with notice period alerts, color-coded urgency indicators, ASC 842 / IFRS 16 schedule generation
- **Landlords** — contact management with vendor ID tracking
- **Transitions** — office closings/moves/new offices with checklist progress tracking
- **HQ HVAC** — heat pumps, PM tasks/log, maintenance contracts, issues, backflows
- **HVAC Contracts** — field office HVAC contract tracking with service scheduling
- **Maintenance Tickets** — work order management with SLA tracking, priority escalation, photo/document attachments
- **Preventive Maintenance** — recurring maintenance tasks across six domains (HVAC, fire & life safety, plumbing & backflow, refuse & waste, exterior & structural, elevators & lifts) with assets, service logs, and regulatory flags. Tasks can **auto-generate work-order tickets** ahead of their due date (configurable lead time, de-duplicated per due cycle) via a nightly scheduler or on demand, and a **PM compliance dashboard** surfaces on-time rates and overdue regulatory work

### Operations & Vendors
- **Vendor Management** — vendor profiles, service categories, compliance tracking
- **Vendor Portal** — self-service login for vendors to view/update assigned work orders and upload completion documents
- **Client Portal** (Pro+) — self-service login for landlords and management companies to manage their secondary contacts, upload/download/remove their own documents, and submit profile change requests for staff approval; admins can revoke or rotate access and review pending requests
- **Insurance Certificates** — COI tracking with expiration alerts for vendors and landlords
- **Attachments** — file upload on any entity; extension whitelist enforced; server-generated storage filenames

### Communication & Automation
- **AI Automation (Google Gemini)** — configurable Gemini model (`GEMINI_MODEL`, `GEMINI_API_KEY`, `GEMINI_API_BASE`) powers lease-document ingestion (extract key terms to pre-fill the lease form — available on all tiers), AI lease-abstract suggestions, and narrative weekly/monthly briefings of upcoming notice periods, expirations, and maintenance. Richer AI beyond basic ingestion is gated to **Pro** and above (`ai_assist`); the service degrades gracefully when no API key is configured
- **Digital Waivers & e-Signatures** — send pre-built or custom waiver templates to any contact, or to a **Visitor** email address where the recipient enters their own details. Captures signer attribution, consent-to-do-business-electronically, IP/user-agent, a tamper-evident document hash, and an immutable audit trail aligned with ESIGN/UETA e-signature standards; a completed PDF is generated on signing. Pro tier and above (`digital_waivers`)
- **Email Reminders** — automated daily notifications for lease expirations, notice deadlines, and HVAC service dates
- **Webhooks** — configurable outbound HTTP events (`ticket.created`, `lease.expiring`, `sla.breached`, etc.) with HMAC-SHA256 signatures and retry logic
- **Notifications** — in-app notification center with per-rule email configuration
- **Real-Time Updates** — WebSocket connection pushes ticket changes, notifications, and dashboard metrics live

### Reporting & Analytics
- **Finance hub** — a dedicated **Finance** navigation section consolidating the **Financial Dashboard**, Rent Roll, Operating Expenses, Reports & Lease Accounting, and Billing
- **Financial Dashboard** — executive overview composing rent-roll obligations, ASC 842 / IFRS 16 ROU asset & lease liability, weighted-average IBR/term, CAM over-budget, and lease-expiration risk, with drill-through links
- **Reports** — generate PDF and CSV exports for any dataset with custom column selection and scheduled delivery; one-click **Quick Export** for rent roll and portfolio maturity
- **Analytics** — portfolio health, cost-per-square-foot trending, lease expiration heatmap, maintenance spend
- **Audit Log** — every mutation tracked with user, timestamp, and before/after state

### Accounting & General Ledger
- **General Ledger** — audit-grade double-entry GL with an org-scoped chart of accounts, balanced journal entries, and a trial balance; lease ASC 842 / IFRS 16 schedules post directly into the ledger
- **Period Close** — fiscal-month accounting periods that can be closed to lock reported financials; postings into a closed period are rejected
- **Journal Export** — QuickBooks-compatible general-journal CSV export for hand-off to external accounting packages
- **CAM Reconciliation** — US-commercial operating-expense recovery reconciliation per lease-year: gross-up to an occupancy standard, tenant pro-rata share, base-year/expense-stop offsets, and controllable-expense caps (cumulative, compounded, or non-cumulative). Statements seed from recorded operating expenses, can be finalized to an immutable record, and post the resulting true-up (tenant owes) or credit (tenant is owed) to the GL
- **Lease Lifecycle Accounting** — audit-grade ASC 842 / IFRS 16 remeasurement for post-commencement events: modifications, renewals/option exercises, and partial or full terminations. Pre-event carrying amounts are read straight off the lease's original schedule, the liability is remeasured to the present value of revised payments, the right-of-use asset is adjusted, and the balancing gain or loss is recognized. Events can be finalized to an immutable record and post the remeasurement, termination penalty, and gain/loss to the GL
- **Accounts Payable (AP-lite)** — vendor bills captured as editable drafts with one or more expense-allocation lines, then finalized to an immutable record that posts `Dr expense / Cr Accounts Payable` to the GL. Payments recorded against a bill post `Dr Accounts Payable / Cr Cash`, and the bill's open/partial/paid status is derived from its payments; an unpaid finalized bill can be voided to reverse its GL entry. USD-only (multi-currency / FX is deferred)
- **Finance access** — General Ledger, CAM, Lease Lifecycle, and Accounts Payable endpoints are restricted to the **admin** and **accountant** roles

### Developer & Integration
- **API Keys** — `om_`-prefixed tokens with bcrypt-hashed storage, scope system (`read:*`, `write:tickets`, etc.), and management UI
- **Stripe Billing** — subscription management, Checkout, Customer Portal, dunning enforcement, webhook event handling
- **Google OAuth** — single sign-on with existing Google accounts

### Security & Access
- **TOTP Two-Factor Authentication** — RFC 6238 TOTP (Google Authenticator, Authy, 1Password); mandatory for super-admins, optional for org users; 8 single-use backup codes per enrollment; see [docs/MFA_SETUP.md](docs/MFA_SETUP.md)
- **Role-Based Access Control** — viewer / editor / accountant / admin / super-admin with org-scoped enforcement
- **Multi-Tenancy** — complete data isolation between organizations; `organization_id` scoped on all entities
- **Rate Limiting** — 200 req/min global; per-user brute-force lockout on login (5 attempts)

### Platform Administration (Super-Admin)
- **Admin Dashboard** — platform-wide KPIs: total orgs, users, tickets, past-due subscriptions, plan breakdown
- **Org Management** — view/edit all organizations; update plan, status, seat limits; impersonate any org
- **User Management** — cross-org user search; activate/deactivate; role changes
- **Billing Management** — subscription status, cancel/restore, Stripe customer IDs
- **Audit Log** — cross-org activity log with full filter set

---

## Roles and Permissions

| Role        | Read | Create/Edit | Delete | Manage Users | Platform Admin |
|-------------|------|-------------|--------|--------------|----------------|
| Viewer      | Yes  | No          | No     | No           | No             |
| Editor      | Yes  | Yes         | No     | No           | No             |
| Accountant  | Yes  | Yes         | No     | No           | No             |
| Admin       | Yes  | Yes         | Yes    | Yes          | No             |
| Super Admin | Yes  | Yes         | Yes    | Yes          | Yes            |

The **accountant** role additionally unlocks the finance-only **General Ledger**, **CAM Reconciliation**, **Lease Lifecycle Accounting**, and **Accounts Payable** endpoints, which are otherwise restricted to admins.

Super-admin accounts require TOTP two-factor authentication — enrollment is enforced on first login. See [docs/MFA_SETUP.md](docs/MFA_SETUP.md).

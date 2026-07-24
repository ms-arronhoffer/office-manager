# Nginx Proxy Manager (NPM)

[Nginx Proxy Manager](https://nginxproxymanager.com/) is the single public
ingress for the Office Manager production stack. It runs as the
`nginx-proxy-manager` service in [`docker-compose.prod.yml`](../../docker-compose.prod.yml)
and is the only container that binds the host's public interface:

| Port | Purpose                                             |
|------|-----------------------------------------------------|
| 80   | Public HTTP (redirected to HTTPS by *Force SSL*)    |
| 443  | Public HTTPS                                        |
| 81   | Admin UI — firewalled to the office CIDR in the SG  |

NPM is attached to the compose stack's shared `edge` network and reaches every
application container **by service name**, so nothing else is published on the
public/LAN interface:

```
frontend domain -> http://frontend:80
admin domain    -> http://admin-frontend:80
landing domain  -> http://landing:80
api domain      -> http://backend:8000   (optional)
```

## Security-group / firewall

Port `81` (admin UI) and port `22` (SSH) are opened only to the trusted office
CIDR in the `office-manager-prod-app` security group — see
[`infra/terraform/aws/ec2.tf`](../terraform/aws/ec2.tf) and the
`ssh_allowed_cidrs` / `npm_admin_allowed_cidrs` variables. Ports `80`/`443` stay
open to the internet so Let's Encrypt can validate certificates and users can
reach the app.

## First run

1. Deploy the stack (the `deploy` job of `.github/workflows/infra-prod.yml`, or
   `docker compose -f docker-compose.prod.yml up -d` on the host).
2. The NPM container seeds a default admin account
   (`admin@example.com` / `changeme`). Log in at `http://<host>:81` **through the
   office network** and change the email/password immediately, **or** set
   `NPM_ADMIN_EMAIL` / `NPM_ADMIN_PASSWORD` to the rotated credentials before
   running the bootstrap script.
3. Point DNS `A` records for each public domain at the instance's public IP
   (`terraform output app_public_ip`).

## Configuring routes (`bootstrap.py`)

Proxy hosts, SSL certificates and the per-host **Block Common Exploits**,
**Websockets Support** and **Force SSL** toggles live in NPM's own database, so
they are provisioned with the idempotent [`bootstrap.py`](./bootstrap.py) helper
rather than declaratively from compose. It uses only the Python standard
library.

Set the domains you want to expose and run it from the host (or anywhere that
can reach the NPM admin API):

```bash
export NPM_LETSENCRYPT_EMAIL="ops@yourdomain.com"
export NPM_FRONTEND_DOMAIN="app.yourdomain.com"
export NPM_ADMIN_DOMAIN="manage.yourdomain.com"
export NPM_LANDING_DOMAIN="www.yourdomain.com"
# Optional: expose the API on its own hostname
# export NPM_API_DOMAIN="api.yourdomain.com"

# Only needed if you rotated the default admin credentials:
# export NPM_ADMIN_EMAIL="you@yourdomain.com"
# export NPM_ADMIN_PASSWORD="…"

python3 infra/nginx-proxy-manager/bootstrap.py
```

Every route is created/updated with:

- a Let's Encrypt certificate (requested if missing, reused if present),
- **Block Common Exploits** enabled,
- **Websockets Support** enabled,
- **Force SSL** + HSTS + HTTP/2 enabled.

The script is **idempotent** — existing proxy hosts (matched by domain) are
updated in place and existing certificates are reused, so it is safe to re-run
on every deploy. Only routes whose `NPM_*_DOMAIN` variable is set are touched.

### Certificate issuance

Let's Encrypt validates over HTTP on port 80, so the domain's DNS must already
resolve to the instance and port 80 must be reachable from the internet. If a
certificate cannot be issued yet, the script logs a warning, still creates the
proxy host over HTTP, and leaves Force SSL off for that host — re-run it once DNS
has propagated to finish enabling SSL.

## Configuration reference

| Variable                 | Default                 | Description                                              |
|--------------------------|-------------------------|----------------------------------------------------------|
| `NPM_BASE_URL`           | `http://localhost:81`   | NPM admin API base URL                                    |
| `NPM_ADMIN_EMAIL`        | `admin@example.com`     | NPM admin login (change after first boot)                |
| `NPM_ADMIN_PASSWORD`     | `changeme`              | NPM admin password (change after first boot)             |
| `NPM_LETSENCRYPT_EMAIL`  | *(unset)*               | Email for Let's Encrypt; unset skips SSL (HTTP only)     |
| `NPM_FRONTEND_DOMAIN`    | *(unset)*               | Public domain → `frontend:80`                            |
| `NPM_ADMIN_DOMAIN`       | *(unset)*               | Public domain → `admin-frontend:80`                      |
| `NPM_LANDING_DOMAIN`     | *(unset)*               | Public domain → `landing:80`                             |
| `NPM_API_DOMAIN`         | *(unset)*               | Optional public domain → `backend:8000`                  |
| `NPM_IMAGE_TAG`          | `2.15.1`                | `jc21/nginx-proxy-manager` image tag (set in compose)    |

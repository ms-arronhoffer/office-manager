# Email Configuration Guide

The Portfolio Desk application includes a built-in Postfix SMTP container for sending emails (report delivery, lease reminders, high-priority ticket alerts). By default it works out of the box on the internal Docker network, but emails sent from `officemanager.local` will be rejected or marked as spam by most mail providers.

Follow this guide to configure a proper sending domain so emails are delivered reliably.

---

## Option A: Use the Built-in SMTP Container with a Real Domain

This keeps the self-contained architecture (no external SMTP dependency) but configures it so recipient mail servers trust your emails.

### 1. Choose a Sending Domain

Pick a domain you own, e.g. `notifications.yourcompany.com`.

### 2. Set Environment Variables

Add these to your `.env` file:

```env
SMTP_DOMAIN=notifications.yourcompany.com
SMTP_FROM=noreply@notifications.yourcompany.com
```

### 3. Add DNS Records

Log into your domain registrar or DNS provider and add the following records.

#### SPF Record

Tells receiving mail servers that your application server is authorized to send email for this domain.

| Type | Name | Value |
|------|------|-------|
| TXT | `notifications.yourcompany.com` | `v=spf1 ip4:YOUR_SERVER_IP -all` |

Replace `YOUR_SERVER_IP` with the public IP address of the machine running Docker Compose.

#### MX Record (optional)

Not strictly required for outbound-only email, but some receiving servers check for it.

| Type | Name | Value | Priority |
|------|------|-------|----------|
| MX | `notifications.yourcompany.com` | `notifications.yourcompany.com` | 10 |

#### A Record

| Type | Name | Value |
|------|------|-------|
| A | `notifications.yourcompany.com` | `YOUR_SERVER_IP` |

#### Reverse DNS (PTR Record)

Contact your hosting provider to set a PTR record for `YOUR_SERVER_IP` pointing to `notifications.yourcompany.com`. Many mail servers reject email from IPs without matching reverse DNS.

### 4. Set Up DKIM Signing (Recommended)

DKIM adds a cryptographic signature to outgoing emails, significantly improving deliverability.

Update the `smtp` service in `docker-compose.yml`:

```yaml
smtp:
  image: boky/postfix
  restart: unless-stopped
  environment:
    ALLOWED_SENDER_DOMAINS: ${SMTP_DOMAIN:-officemanager.local}
    HOSTNAME: ${SMTP_DOMAIN:-officemanager.local}
    DKIM_AUTOGENERATE: "true"
  volumes:
    - dkim_keys:/etc/opendkim/keys
  networks:
    - internal
```

Add the volume at the bottom of the file:

```yaml
volumes:
  pgdata:
  uploads:
  dkim_keys:
```

After starting the container, retrieve the generated DKIM public key:

```bash
docker compose exec smtp cat /etc/opendkim/keys/*/mail.txt
```

Add the output as a TXT record in your DNS:

| Type | Name | Value |
|------|------|-------|
| TXT | `mail._domainkey.notifications.yourcompany.com` | *(paste the key from the command above)* |

### 5. Add a DMARC Record

DMARC ties SPF and DKIM together and tells receiving servers what to do with unauthenticated mail.

| Type | Name | Value |
|------|------|-------|
| TXT | `_dmarc.notifications.yourcompany.com` | `v=DMARC1; p=quarantine; rua=mailto:dmarc@yourcompany.com` |

### 6. Restart and Test

```bash
docker compose down && docker compose up -d --build
```

Verify DNS propagation (may take up to 48 hours):

```bash
dig TXT notifications.yourcompany.com
dig TXT mail._domainkey.notifications.yourcompany.com
dig TXT _dmarc.notifications.yourcompany.com
```

Send a test email from the Reports page and check delivery.

---

## Option B: Use an External SMTP Provider

If you prefer a managed email service (Office 365, Gmail/Google Workspace, SendGrid, Amazon SES, etc.), bypass the built-in SMTP container entirely.

### 1. Set Environment Variables

```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USER=your-service-account@yourcompany.com
SMTP_PASSWORD=your-app-password
SMTP_FROM=noreply@yourcompany.com
```

Common provider settings:

| Provider | Host | Port | Notes |
|----------|------|------|-------|
| Office 365 | `smtp.office365.com` | 587 | Use an app password if MFA is enabled |
| Google Workspace | `smtp.gmail.com` | 587 | Requires app-specific password |
| SendGrid | `smtp.sendgrid.net` | 587 | Use API key as password, `apikey` as username |
| Amazon SES | `email-smtp.us-east-1.amazonaws.com` | 587 | Use IAM SMTP credentials |

### 2. (Optional) Remove the Built-in SMTP Container

If you won't use the built-in container, you can remove the `smtp` service from `docker-compose.yml` and remove the `smtp` dependency from the `backend` service.

### 3. Restart

```bash
docker compose down && docker compose up -d --build
```

When `SMTP_USER` is set, the application automatically uses authenticated TLS connections instead of the unauthenticated local relay.

---

## Verifying Email Delivery

1. **Check backend logs** for send status:
   ```bash
   docker compose logs backend | grep EMAIL
   ```

2. **Use the Email Log** tab on the Email Rules page to see send history and status.

3. **Test with mail-tester.com**: Send a report email to your test address at [mail-tester.com](https://www.mail-tester.com) to get a deliverability score and identify any missing DNS records.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `[EMAIL SKIPPED]` in logs | `SMTP_HOST` is empty | Set `SMTP_HOST=smtp` in `.env` (or it defaults to `smtp` automatically) |
| `Connection refused` | SMTP container not running | Run `docker compose up -d smtp` |
| Emails land in spam | Missing SPF/DKIM/DMARC | Add DNS records per Option A above |
| `Authentication failed` | Wrong credentials for external SMTP | Verify `SMTP_USER` and `SMTP_PASSWORD` |
| `STARTTLS error` with built-in container | Built-in container doesn't use TLS | Ensure `SMTP_USER` is empty when using the built-in container |

---

## Environment Variable Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `SMTP_DOMAIN` | `officemanager.local` | Domain used by the built-in Postfix container |
| `SMTP_HOST` | `smtp` | SMTP server hostname |
| `SMTP_PORT` | `25` | SMTP server port (use 587 for external providers) |
| `SMTP_USER` | *(empty)* | SMTP username — leave empty for built-in container |
| `SMTP_PASSWORD` | *(empty)* | SMTP password — leave empty for built-in container |
| `SMTP_FROM` | `noreply@officemanager.local` | Sender address for all outgoing emails |

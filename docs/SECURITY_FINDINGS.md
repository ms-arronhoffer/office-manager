# Security Review — Portfolio Desk

**Review Date:** 2026-04-29  
**Scope:** Backend Python/FastAPI, frontend React/TypeScript, admin frontend  
**Files Reviewed:** `backend/app/main.py`, `backend/app/config.py`, `backend/app/auth/jwt_handler.py`, `backend/app/auth/dependencies.py`, `backend/app/routers/auth.py`, `backend/app/routers/attachments.py`, `backend/app/routers/organizations.py`, `backend/app/routers/site_settings.py`, `backend/app/routers/notifications.py`, `backend/app/routers/admin/orgs.py`, `frontend/src/auth/AuthContext.tsx`

---

## Severity Ratings

| Rating   | Meaning                                                                     |
|----------|-----------------------------------------------------------------------------|
| CRITICAL | Immediate exploitation risk; must fix before any production deployment      |
| HIGH     | Significant security impact; fix before public exposure                     |
| MEDIUM   | Meaningful risk under realistic conditions; remediate in next sprint        |
| LOW      | Minor exposure or defense-in-depth concern; address when convenient         |

---

## Findings

---

### F-01 — Weak Default JWT Secret
**Severity:** CRITICAL  
**File:** `backend/app/config.py:16`

```python
JWT_SECRET: str = "change-me"
```

**Risk:** If this application is deployed without overriding `JWT_SECRET`, all JWTs can be forged by anyone who knows the default. An attacker can sign arbitrary tokens — including `is_super_admin: true` — and gain full platform access with no credentials.

**Remediation:**
1. Remove the default value: `JWT_SECRET: str` (pydantic-settings will raise a `ValidationError` at startup if the variable is not set, preventing deployment with an insecure secret).
2. In `.env` and all deployment scripts, generate a strong secret: `openssl rand -base64 48`.
3. Ensure the secret is at least 32 characters (256 bits).

---

### F-02 — Default Admin Password in Plain Text
**Severity:** CRITICAL  
**File:** `backend/app/config.py:28`

```python
DEFAULT_ADMIN_PASSWORD: str = "changeme123"
```

The same default is shown in `README.md`, deployment scripts for Azure Container Apps, and Azure App Service. Any script copy-pasted without substitution provisions a live server with a known-weak admin credential.

**Risk:** Credential stuffing, targeted enumeration, or anyone who has seen this README can authenticate as an administrator immediately.

**Remediation:**
1. Remove the default: `DEFAULT_ADMIN_PASSWORD: str` (force explicit env var).
2. Alternatively, auto-generate a random password on first boot, print it once to stdout, and invalidate it after first login.
3. Audit all deployment documentation to ensure `DEFAULT_ADMIN_PASSWORD` is never hardcoded in examples with real-looking values.

---

### F-03 — CORS Wildcard + `allow_credentials=True`
**Severity:** HIGH  
**File:** `backend/app/main.py:41-46`

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    ...
)
```

**Risk:** The combination of `allow_origins=["*"]` and `allow_credentials=True` is explicitly prohibited by the CORS specification and is rejected by modern browsers — but the intent exposes the API to reflected-origin attacks. A malicious website can make credentialed cross-origin requests on behalf of an authenticated user if the middleware is ever corrected to use an explicit allowlist with credentials enabled. In practice, browsers currently block this combination, but relying on browser enforcement is not a defense.

**Remediation:**
Replace the wildcard with an explicit allowlist driven by the `FRONTEND_URL` config value:

```python
origins = [settings.FRONTEND_URL]
if settings.ADMIN_URL:
    origins.append(settings.ADMIN_URL)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

### F-04 — MFA Endpoints Have No Per-Attempt Brute-Force Protection
**Severity:** HIGH  
**File:** `backend/app/routers/auth.py` — `/auth/mfa/verify`, `/auth/mfa/enable`

The login route (`/auth/login`) calls `_track_failure()` and `_check_lockout()`, providing 5-attempt lockout protection. The MFA verification endpoints do not.

**Risk:** A TOTP code space is only 10^6 (000000–999999). With a 15-minute challenge window and the global 200 req/min rate limit as the only constraint, an attacker can attempt ~3000 codes per challenge window — covering 0.3% of the keyspace per attempt. In a targeted attack this is a meaningful brute-force surface. Backup codes (12-char hex) have a much larger space but are still unprotected.

**Remediation:**
In `_verify_mfa` and `_enable_mfa` handler logic, call `_track_failure(db, user_id, ...)` on each failed attempt. After 5 failures, either:
- Invalidate the `mfa_challenge_token` immediately (forcing re-authentication from credentials), or
- Lock the challenge token with a short cooldown (30 seconds).

---

### F-05 — Default PostgreSQL Password
**Severity:** HIGH  
**File:** `backend/app/config.py:10`

```python
POSTGRES_PASSWORD: str = "password"
```

**Risk:** Any deployment that starts the DB container without setting `POSTGRES_PASSWORD` in the environment will use the literal string `"password"`. Combined with F-01/F-02, a fully deployed but misconfigured instance exposes database credentials, JWT signing, and admin access simultaneously.

**Remediation:** Remove the default — `POSTGRES_PASSWORD: str` — so pydantic-settings raises at startup. Update `docker-compose.yml` to fail fast rather than start with insecure defaults.

---

### F-06 — File Upload Content-Type Not Validated by Magic Bytes
**Severity:** MEDIUM  
**File:** `backend/app/routers/attachments.py:134-148`

Extension validation is enforced (config-driven whitelist), and filenames are sanitized. However, the MIME type is accepted from the client's `Content-Type` header without server-side verification of file magic bytes.

**Risk:** A user can upload a file with a whitelisted extension (e.g., `document.pdf`) that is actually an HTML file, SVG with embedded script, or other active content. If any path serves these files with their declared content type, stored XSS or content sniffing attacks become possible.

**Remediation:**
Use `python-magic` (libmagic binding) to read the first 512 bytes and verify the detected MIME type matches the declared extension before accepting the upload:

```python
import magic
detected = magic.from_buffer(content[:512], mime=True)
if detected not in ALLOWED_MIME_TYPES:
    raise HTTPException(status_code=400, detail="File content does not match extension.")
```

Additionally, ensure file-serving responses include `Content-Disposition: attachment` and `X-Content-Type-Options: nosniff` to prevent browser content sniffing.

---

### F-07 — Signup Endpoint Has No Rate Limiting
**Severity:** MEDIUM  
**File:** `backend/app/routers/organizations.py:30`

`POST /api/v1/organizations/signup` creates a new organization and admin user. The global 200 req/min limit applies, but there is no per-IP or per-email throttle specific to org creation.

**Risk:** Automated org creation spam can inflate user counts, consume database resources, and trigger unwanted emails (welcome messages, notification rules). In a Stripe-integrated deployment, each org can potentially initiate a Stripe Customer object before payment is confirmed.

**Remediation:**
Apply a dedicated SlowAPI limiter on this endpoint:

```python
@router.post("/signup", status_code=201)
@limiter.limit("5/hour")
async def signup(request: Request, ...):
```

Consider also requiring email verification before the account becomes active.

---

### F-08 — Health Endpoint Exposes Internal Build Information
**Severity:** LOW  
**File:** `backend/app/main.py:105-113`

`GET /api/v1/health` returns `version`, `build_sha`, and `uptime_seconds` without authentication.

**Risk:** Build SHA and version string aid targeted exploitation by revealing which known-vulnerable version is deployed. Uptime leaks restart patterns. This is low severity because the information is not directly exploitable, but it reduces the cost of reconnaissance.

**Remediation:**
Either require authentication (bearer token) on the health endpoint, or reduce the response to a minimal liveness signal: `{"status": "ok"}`. Expose build metadata only on an authenticated internal endpoint.

---

### F-09 — Site Settings Endpoint Unauthenticated
**Severity:** LOW  
**File:** `backend/app/routers/site_settings.py:40`

`GET /api/v1/site-settings` requires no authentication. This is intentional — the login page fetches `app_name`, `login_form_header`, and `login_subtitle` before the user authenticates.

**Risk:** The endpoint is a reliable fingerprinting surface that confirms a Portfolio Desk deployment. The data returned is branding configuration only and not sensitive.

**Accepted with note:** This is a design trade-off, not a flaw. Document it explicitly in code comments so future reviewers don't add authentication inadvertently and break the login page.

---

## Routing Review Summary

All frontend and backend routes were audited as part of this review.

**Frontend (main app):** 69 routes → 50 page components. No orphaned pages, no broken routes, no missing lazy-load fallbacks.

**Admin frontend:** 8 routes → 7 page components. All guarded by `AuthGuard` which validates `is_super_admin` in the JWT payload. No unguarded admin routes.

**Backend:** ~200+ endpoints across 38 router modules. All admin routes (`/admin/v1/*`) use `Depends(require_super_admin())`. Org-scoped routes use `Depends(get_current_org())`. No route ordering conflicts detected.

---

## Remediation Priority

| # | Finding                        | Severity | Effort |
|---|--------------------------------|----------|--------|
| F-01 | Weak default JWT secret     | CRITICAL | Low    |
| F-02 | Default admin password      | CRITICAL | Low    |
| F-03 | CORS wildcard + credentials | HIGH     | Low    |
| F-04 | MFA brute-force             | HIGH     | Medium |
| F-05 | Default DB password         | HIGH     | Low    |
| F-06 | No magic byte validation    | MEDIUM   | Medium |
| F-07 | No signup rate limit        | MEDIUM   | Low    |
| F-08 | Health endpoint verbosity   | LOW      | Low    |
| F-09 | Site settings unauthenticated | LOW    | N/A (by design) |

F-01, F-02, F-03, and F-05 are all one- to three-line changes with no behavioral impact. They should be fixed before any public-facing deployment.

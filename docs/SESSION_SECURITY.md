# Session and Browser Security

## Browser sessions

The primary and admin SPAs authenticate with cookies. They do not persist JWTs
in `localStorage` or place JWTs in WebSocket query strings.

- `om_access`: httpOnly, SameSite=Lax, path `/`, 30 minute default lifetime.
- `om_refresh`: httpOnly, SameSite=Strict, path `/api/v1/auth`, 7 day lifetime.
- `om_csrf`: script-readable, SameSite=Strict, path `/`. Axios sends its value
  as `X-CSRF-Token` for mutations.
- Cookies are marked `Secure` when `APP_ENV` is `production`, `prod`, or
  `staging`.

Refresh tokens are random opaque values. Only SHA-256 hashes are stored in
`refresh_sessions`. Every refresh locks and revokes the current record, creates
a replacement in the same family, and returns new access and refresh cookies.
Reuse of a revoked token revokes every active member of that family.

Password reset and user deactivation revoke active refresh sessions. Users can
review sessions, revoke an individual session, or sign out other devices from
Settings.

## API clients

Bearer JWTs and `om_` API keys remain supported in the `Authorization: Bearer`
header. Password, Google, signup, and MFA responses still include
`access_token` for compatibility. API clients do not need CSRF headers when
using Authorization headers.

Existing clients that call `POST /api/v1/auth/refresh` with a valid bearer JWT
continue to receive a JSON access token. Browser clients should use cookies,
send credentials, and call refresh without a request body.

## SSO and WebSockets

SSO callbacks set cookies on the redirect response and return only
`#sso_success=1`. No JWT is placed in the URL. Browser WebSockets authenticate
from `om_access`; the legacy `?token=` parameter remains temporarily available
for non-browser clients.

## Portal links

Resident, client, owner, vendor, and waiver links use a URL token only for the
initial handoff. Each frontend exchanges it for a scoped httpOnly,
SameSite=Strict cookie and immediately calls `history.replaceState` to remove
the token. Legacy portal headers remain accepted during migration.

The current portal account schemas still contain plaintext persistent portal
tokens for compatibility. Hashing those columns requires a separate data
migration with a dual-read rollout. URL exchange prevents browser history and
referrer exposure now.

## Proxy headers and TLS

The frontend, admin, and landing nginx configurations send CSP,
`Referrer-Policy: no-referrer`, Permissions-Policy, frame protection,
`X-Content-Type-Options: nosniff`, and `X-XSS-Protection: 0`.

Set HSTS at the TLS terminator, not the port 80 application containers. For
Nginx Proxy Manager, add this to the HTTPS advanced configuration after the
domain is confirmed to work exclusively over TLS:

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

Add `preload` only after every subdomain is permanently HTTPS and the domain is
ready for browser preload submission. Preserve `Host`, `X-Forwarded-For`, and
`X-Forwarded-Proto` when proxying to the application.
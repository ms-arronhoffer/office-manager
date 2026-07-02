# Two-Factor Authentication (TOTP) Setup

Portfolio Desk uses RFC 6238 time-based one-time passwords (TOTP) for two-factor authentication, compatible with Google Authenticator, Authy, and 1Password.

---

## Who Uses 2FA

| Account Type  | 2FA Status           | Details                                                              |
|---------------|----------------------|----------------------------------------------------------------------|
| Super Admin   | **Mandatory**        | Enrollment is enforced on first login — no path to a JWT without it |
| Org User      | Optional             | Can be enabled/disabled from account settings                        |

---

## Super-Admin First Login (Forced Enrollment)

When a super-admin account logs in without TOTP enabled, the backend returns an `mfa_setup_required` flag instead of a JWT. The admin frontend walks through the following flow:

### Step 1 — Enter Credentials
Log in at `http://localhost:4001` with email and password. Because TOTP is not yet enrolled, the server responds with `{ "mfa_setup_required": true, "mfa_token": "..." }`.

### Step 2 — Scan QR Code
The frontend fetches a QR code and setup key from `POST /api/v1/auth/mfa/setup`. Open your authenticator app and scan the QR code, or enter the manual setup key if scanning isn't possible. The "Copy key" button copies the setup key to your clipboard.

> Supported apps: Google Authenticator, Authy, 1Password, Microsoft Authenticator, Bitwarden, and any RFC 6238-compatible TOTP app.

### Step 3 — Confirm Your App
Enter the 6-digit code currently shown in your authenticator app and click **Enable 2FA**. This calls `POST /api/v1/auth/mfa/enable`.

### Step 4 — Save Backup Codes
After TOTP is confirmed, 8 single-use backup codes are displayed **one time only**. Each code is 12 characters.

**Copy all codes and store them in a password manager before continuing.** They cannot be retrieved again after this screen.

Click **I've saved my backup codes — Continue** to complete enrollment and enter the admin interface.

---

## Subsequent Super-Admin Logins

On every login after initial enrollment:

1. Enter email and password — the server returns `{ "mfa_required": true, "mfa_token": "..." }`
2. Enter the 6-digit code from your authenticator app and click **Verify**
3. If you no longer have access to your authenticator app, toggle **Use a backup code instead** and enter one of your 12-character backup codes

> Each backup code can only be used once. After all 8 are consumed, you must contact another super-admin to reset your TOTP enrollment.

---

## Regular User 2FA (Optional)

Org users can enable TOTP from their account settings page. The flow is identical to the enrollment steps above. Once enabled, they will be prompted for a TOTP code on every login.

To disable 2FA, go to account settings and enter your current TOTP code (or a backup code) to confirm.

---

## Technical Details

| Detail                 | Value                                                            |
|------------------------|------------------------------------------------------------------|
| Algorithm              | TOTP (RFC 6238), HMAC-SHA1, 30-second window                    |
| Clock skew tolerance   | ±30 seconds (valid_window=1)                                     |
| Secret format          | Base32-encoded 160-bit random secret                             |
| Challenge token        | `secrets.token_hex(32)` (256-bit), stored in DB, expires 15 min |
| Backup codes           | 8 × 12-character hex strings, bcrypt-hashed at rest             |
| Issuer name in app     | "Portfolio Desk"                                                 |

### Challenge Token Flow

The `mfa_token` returned by `/login` is **not a JWT**. It is a single-use, 15-minute opaque token that bridges credential verification and TOTP verification without issuing a full JWT prematurely. It is stored in `users.mfa_challenge_token` and cleared on any success path.

### API Endpoints

All MFA endpoints are unauthenticated (they use the `mfa_token` in the body for authorization):

| Method | Path                        | Body                        | Returns                                     |
|--------|-----------------------------|-----------------------------|---------------------------------------------|
| POST   | `/api/v1/auth/mfa/setup`    | `{mfa_token}`               | `{secret, qr_uri}`                          |
| POST   | `/api/v1/auth/mfa/enable`   | `{mfa_token, code}`         | `{access_token, backup_codes: [8 strings]}` |
| POST   | `/api/v1/auth/mfa/verify`   | `{mfa_token, code}`         | `{access_token}`                            |
| POST   | `/api/v1/auth/mfa/disable`  | `{code}` (JWT required)     | `{message}`                                 |

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Invalid authentication code" on first try | Clock skew between your device and server | Sync your device's time; the ±30s window should cover minor drift |
| Lost access to authenticator app | Device lost/replaced | Use one of your saved backup codes |
| All backup codes exhausted | Consumed over time or all codes lost | Contact a second super-admin to reset your TOTP enrollment via `POST /api/v1/auth/mfa/disable` on your behalf (requires a valid code from their session) |
| QR code won't scan | Camera / lighting issue | Use the "Copy key" button to manually enter the setup key in your authenticator app |
| "This account does not have super-admin access" on admin login | Logging in with an org-level admin account | The admin frontend (`/admin`) only accepts `is_super_admin=true` accounts |

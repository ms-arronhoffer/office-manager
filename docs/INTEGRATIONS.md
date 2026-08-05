# External integrations

Setup and operation of the five external services the app talks to. All of them
are **optional**: with credentials unset each degrades to a documented no-op
rather than breaking the feature that uses it.

| Integration | Purpose | Required plan | Config prefix |
|---|---|---|---|
| Payments | Resident rent payments from the portal | any | `PAYMENTS_` |
| Screening | Credit / criminal / eviction reports | any (residential) | `SCREENING_` |
| SSO | OIDC single sign-on | Enterprise | `SSO_` |
| QuickBooks Online | Push journal entries, map accounts | Operations | `QBO_` |
| Plaid | Live bank feed into reconciliation | Operations | `PLAID_` |

> **Nothing here has been exercised against a live provider.** Every integration
> is written against the vendors' documented APIs but no token has been
> exchanged, no journal entry pushed and no transaction imported. Run each in
> sandbox first and expect to correct field names, date formats and pagination
> on first contact.

---

## Prerequisite: `ENCRYPTION_KEY`

SSO, QuickBooks and Plaid all persist long-lived credentials. Those are
encrypted at rest through `app.utils.crypto`, which reads `ENCRYPTION_KEY`.

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set it **before** connecting anything. When it is unset, `encrypt_secret`
raises unless `APP_ENV` is a development value (`development`, `dev`, `local`,
`test`, `testing`). That is deliberate: an OAuth refresh token or Plaid access
token written in plaintext is worse than a failed connection. The first connect
attempt on a misconfigured deployment fails loudly, which looks like a bug if
you are not expecting it.

Rotating the key invalidates every stored secret. Existing connections must be
reconnected. Rows written before this behaviour existed are prefixed `plain:`
and still decrypt, so upgrading is safe.

---

## Payments (resident rent)

Charges a resident's tokenised card or bank account from the resident portal.
Targets a Stripe-style PaymentIntents API.

```bash
PAYMENTS_PROVIDER=stripe
PAYMENTS_API_KEY=sk_test_...
PAYMENTS_API_URL=              # override only for a non-Stripe or sandbox endpoint
```

Unset, `charge_payment` returns `status="unconfigured"` and captures nothing.
The portal still records the payment intent and tells the resident no money was
taken, so the ledger stays consistent without a processor.

### Flow

1. Resident opens **Make a payment** in the portal. The client generates one
   idempotency key per attempt (`crypto.randomUUID()`).
2. `POST /api/v1/resident-portal/payments` validates the amount is positive and
   not greater than the outstanding balance.
3. Invoices are allocated **oldest first**, resolved before any write.
4. A single charge is sent for the whole payment with the idempotency key.
5. Receipts are recorded through the same `rent_service.record_rent_payment`
   path staff use, so the GL and AR aging are identical either way.

### Idempotency

The key is stable for one payment attempt and resent on retry, so a
double-click or network retry settles onto the same transaction instead of
charging twice. If an older client omits it, the server derives one from a
digest of resident, amount and the exact invoice allocation, which still
collapses a duplicate submit.

### Security

Raw card and bank numbers never reach the application. `resident_payment_methods`
stores only the opaque processor token plus `brand` and `last4` for display.

---

## Tenant screening

```bash
SCREENING_PROVIDER=transunion
SCREENING_API_KEY=...
SCREENING_API_URL=...
SCREENING_POLL_ATTEMPTS=5
SCREENING_POLL_INTERVAL_SECONDS=2.0
```

Unset, `request_screening` returns a `manual` report with a `review`
recommendation so the leasing funnel is never blocked.

### FCRA obligations you own

Enabling this makes you a user of consumer reports. The code deliberately does
not, and cannot, discharge these for you:

- **Permissible purpose** must be established before each request.
- **Adverse action notices** are required when a report contributes to a
  decline. A `decline` recommendation populates an `adverse_action` block
  (reason codes, provider reference, agency name, phone and address) inside
  `report_data` so you have what the notice requires.
- **Dispute handling** must route the applicant to the reporting agency.
- **Retention and disposal** of consumer report data is regulated.

### PII minimisation

`summarize_report` uses an **allowlist**, so an unrecognised provider field can
never leak into storage. Deliberately discarded: SSN, full date of birth, street
address, tradeline detail and the raw report body. Retained: score band,
derogatory counts, reason codes, verification flags and the provider reference.

---

## Single sign-on (OIDC)

Server-level config is one value. The IdP itself is configured **per
organization** in-app under Administration → SSO, because each customer brings
their own tenant.

```bash
SSO_CALLBACK_URL=https://api.example.com/api/v1/sso/callback
```

This must be reachable by the IdP and registered on it as a redirect URI,
exactly as written.

### Per-organization setup

In the app, an admin on the Enterprise plan supplies:

| Field | Notes |
|---|---|
| Issuer | Must be `https`, no query or fragment. Example: `https://login.microsoftonline.com/<tenant>/v2.0` |
| Client ID | From the IdP app registration |
| Client secret | Encrypted at rest, only ever shown back as a masked hint |
| Allowed email domains | Exact match. `contoso.com` does **not** admit `evil.contoso.com` |
| Default role | Role granted on first login: viewer, editor, accountant or admin |
| Enforce SSO | Refuses password login for this org (super-admins exempt) |

### Flow

`GET /sso/lookup` → `GET /sso/{org_slug}/authorize` → IdP consent →
`GET /sso/callback` → redirect to the SPA with the result in the **URL
fragment**, so tokens never reach a server access log or a `Referer` header.

### What is enforced

- ID token signature verified against the IdP JWKS; `iss`, `aud` and `exp`
  checked; algorithms allowlisted to RS/ES families.
- `nonce` matched to the specific login request.
- `state` is single-use and expires after 10 minutes, enforced by a database
  unique constraint rather than a cookie, so it holds across API workers.
- Discovery and JWKS URLs are pinned to the issuer's own origin, which blocks an
  admin-supplied issuer from pointing metadata lookups at an internal host.
- Unverified email addresses are refused.
- An account belonging to another organization is refused rather than moved.
- TOTP still applies: an enrolled user completes MFA before receiving a session.

---

## QuickBooks Online

```bash
QBO_CLIENT_ID=...
QBO_CLIENT_SECRET=...
QBO_REDIRECT_URI=https://app.example.com/finance/connections
QBO_ENVIRONMENT=production
QBO_API_BASE_URL=https://quickbooks.api.intuit.com/v3/company
```

Sandbox uses `https://sandbox-quickbooks.api.intuit.com/v3/company`.

### Setup

1. Create an app at developer.intuit.com. Required scope is
   `com.intuit.quickbooks.accounting` (already requested by the client).
2. Register the redirect URI. It points at the app's **connections page**, not
   the API, because the page trades the code for tokens. It must match
   `QBO_REDIRECT_URI` byte for byte or Intuit rejects the request.
3. Connect at **Finance → Connections → Connect QuickBooks**. Intuit redirects
   back with `code` and `realmId`, which the page posts to `/quickbooks/callback`.
4. Click **Pull chart of accounts**. It auto-matches what it can; map the rest
   by hand. Unmapped accounts are the usual reason entries get skipped.
5. **Sync now** pushes posted journal entries incrementally by cursor.

### Correctness guarantees

- Only balanced, posted entries are pushed. Unposted and unbalanced entries are
  skipped, never partially written.
- Each entry carries a stable external reference, so a retry adopts the existing
  QuickBooks entry instead of double-posting.
- Access tokens refresh automatically ahead of expiry
  (`QBO_TOKEN_REFRESH_LEEWAY_SECONDS`).

---

## Plaid (live bank feed)

```bash
PLAID_CLIENT_ID=...
PLAID_SECRET=...
PLAID_ENV=production
PLAID_API_BASE_URL=https://production.plaid.com
PLAID_COUNTRY_CODES=US
PLAID_REDIRECT_URI=https://app.example.com/finance/connections
```

Sandbox uses `https://sandbox.plaid.com` with test login `user_good` /
`pass_good`.

### Setup

1. Create the app in the Plaid dashboard and enable the **Transactions**
   product.
2. `PLAID_REDIRECT_URI` is optional but **required for OAuth banks** (Chase,
   Wells Fargo and similar), which redirect out to their own site and back.
   Without it those institutions fail while smaller banks succeed, which is a
   confusing way to discover the setting. Register the same URI in the Plaid
   dashboard.
3. Create a ledger bank account under Finance → Bank Reconciliation first.
   Imported transactions need somewhere to land, and the UI blocks connection
   until one exists.
4. Connect at **Finance → Connections → Connect a bank**. Plaid Link opens in
   its own iframe; credentials are entered there and never touch this
   application.
5. **Sync** pulls via cursor-based `/transactions/sync`, handling added,
   modified and removed transactions without reprocessing.

Transactions land in the same model the CSV/OFX import writes to, so
reconciliation is unchanged.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Connect raises about `ENCRYPTION_KEY` | Key unset and `APP_ENV` is not a dev value. Working as designed. |
| Intuit rejects the redirect | `QBO_REDIRECT_URI` differs from the app registration, including trailing slash |
| QuickBooks sync skips everything | Accounts unmapped. Pull the chart of accounts and map them. |
| Small banks connect, Chase fails | `PLAID_REDIRECT_URI` unset or not registered with Plaid |
| Payment reports `unconfigured` | `PAYMENTS_API_KEY` unset. Payment recorded, no money taken. |
| Screening always says "review" | `SCREENING_API_KEY` unset |
| SSO callback returns `verification_failed` | Check `aud` matches the client ID, `iss` matches the configured issuer, and the email domain is allowed |

See also [MIGRATIONS.md](MIGRATIONS.md), since every integration above needs the
schema from revisions 111 to 115.

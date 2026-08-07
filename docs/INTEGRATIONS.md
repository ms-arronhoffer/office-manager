# External integrations

Setup and operation of the six external integration surfaces. All of them
are **optional**: with credentials unset each degrades to a documented no-op
rather than breaking the feature that uses it.

| Integration | Purpose | Required plan | Config prefix |
|---|---|---|---|
| Platform Stripe | SaaS subscriptions and invoices | platform | `STRIPE_` |
| Payments | Resident rent payments from the portal | any | tenant config; legacy `PAYMENTS_` fallback |
| Screening | Credit / criminal / eviction reports | any (residential) | tenant config; legacy `SCREENING_` fallback |
| SSO | OIDC single sign-on | Enterprise | `SSO_` |
| QuickBooks Online | Push journal entries, map accounts | Operations | `QBO_` |
| Plaid | Live bank feed into reconciliation | Operations | tenant config; legacy `PLAID_` fallback |

> **No live certification was performed in this environment.** Real provider
> credentials are required to establish sandbox or live readiness. Unit and
> contract tests prove application behavior against controlled HTTP responses;
> they are not evidence that a vendor account, product entitlement, webhook, or
> production settlement path is correctly configured.

## Verification matrix

The organization-admin endpoint `GET /api/v1/integrations/readiness` reports
configuration gaps and available evidence without returning secrets or tokens.
`POST /api/v1/integrations/{provider}/verify` performs only supported,
non-mutating checks. Platform Stripe is intentionally absent because it is not
a tenant/user integration.

| Integration | Automated contract evidence | Safe sandbox smoke | Persisted/provider evidence | Current certification |
|---|---|---|---|---|
| Platform Stripe billing | Account/auth errors, billing lifecycle, webhook behavior | `GET /v1/account` with `sk_test_...` | Platform config stores last verification time/result | Not live-certified here |
| Resident Stripe payments | PaymentIntent form body, idempotency, success/error shapes | `GET /v1/account` with `sk_test_...`; no PaymentIntent created | Tenant row stores last verification time/result | Not live-certified here |
| Screening | Response normalization, polling/error shapes, PII allowlist | Provider-documented `SCREENING_HEALTH_URL` GET only | Unsupported when vendor has no non-mutating endpoint | Sandbox report required; not live-certified here |
| QuickBooks Online | OAuth refresh rotation, errors/retry, pagination, journal payloads | Read-only `SELECT * FROM CompanyInfo` against sandbox | Successful OAuth exchange/connection and sync status | Not live-certified here |
| Plaid | Credential body, error codes, cursor pagination, modified/removed transactions | `/institutions/get` with count 1; no Item created | Tenant row stores last verification time/result | Not live-certified here |
| OIDC SSO | Discovery/token/error shapes, signature/issuer/audience/nonce/domain checks | Discovery document GET against a test tenant | Successful login time is full-flow evidence | Not live-certified here |

The opt-in `.github/workflows/integration-smoke.yml` uses the protected
`integration-sandbox` repository environment. Each check skips with the missing
secret names when credentials are absent. The test code refuses Stripe live
keys and provider URLs that are not recognizably sandbox/test endpoints.

## Manual certification checklist

Complete this once per provider account and again after credential, API version,
webhook, redirect URI, product entitlement, or production-mode changes.

| Integration | Required certification actions | Evidence fields to retain |
|---|---|---|
| Platform Stripe billing | Verify account access; create/cancel a test subscription; deliver and replay signed webhook; confirm invoice, entitlement and failed-payment state | provider account id, mode, test customer/subscription/invoice ids, webhook event ids, timestamps, operator, build SHA, screenshots/log links |
| Resident Stripe payments | Use Stripe test PaymentMethods for successful card, decline, ACH processing and idempotent retry; confirm no raw payment data is stored; reconcile test receipt | account id, PaymentIntent ids, idempotency key hash, receipt ids, expected/actual statuses, timestamps, operator, build SHA |
| Screening | Confirm permissible-purpose workflow with counsel/vendor; run vendor-approved synthetic applicant for complete/pending/decline; verify adverse-action fields and PII minimization | sandbox report ids, synthetic applicant id, provider product/package, status sequence, retained-field export, legal approval reference, timestamp/operator/build SHA |
| QuickBooks Online | Complete sandbox OAuth; pull paginated accounts; map accounts; push one balanced posted journal; retry and prove no duplicate; force token refresh | realm id, QBO journal id/DocNumber, mapping export, refresh timestamp, sync log id, before/after screenshots, operator/build SHA |
| Plaid | Open Sandbox Link with `user_good`; connect a test institution; sync multiple pages; simulate modified/removed transaction and `ITEM_LOGIN_REQUIRED`; disconnect | item id, institution/account masks only, cursor hashes, imported transaction ids, error/recovery timestamps, operator/build SHA |
| OIDC SSO | Validate discovery/JWKS; sign in with allowed and denied domains; test nonce/state replay, expiry, wrong audience/issuer, disabled user, enforce-SSO and break-glass access | issuer/tenant id, app registration id, test user ids, redirect URI, test case results, token claim summary without token, timestamps/operator/build SHA |

Record sandbox and live evidence separately. A sandbox pass does not certify live
merchant onboarding, bank access, screening compliance, IdP policy, network
allowlists, webhook delivery, settlement, or production entitlements.

---

## Prerequisite: `ENCRYPTION_KEY`

SSO, QuickBooks, Payments, Screening and Plaid persist long-lived credentials. Those are
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

Organization admins configure Payments under **Finance > Connections**. The
secret API key is encrypted at rest and only a masked hint is returned. The
`PAYMENTS_*` variables below are legacy fallback/bootstrap values used only
when no tenant row exists. Save the fallback in the tenant form to migrate it.

Cards and ACH use different Stripe APIs. Cards use PaymentIntents with a
client-created `pm_...` PaymentMethod. Plaid Auth returns a short-lived Stripe
processor bank token (`btok_...`), which the backend attaches to a tenant Stripe
Customer through `POST /v1/customers/{customer}/sources`. Stripe returns a
reusable bank source (`ba_...`). A `btok_...` is not a modern `pm_...`
PaymentMethod and must not be sent to PaymentIntents.

```bash
PAYMENTS_PROVIDER=stripe
PAYMENTS_API_KEY=sk_test_...
PAYMENTS_PUBLISHABLE_KEY=pk_test_...
PAYMENTS_API_URL=              # override only for a non-Stripe or sandbox endpoint
```

Unset, `charge_payment` returns `status="unconfigured"` and captures nothing.
The portal still records the payment intent and tells the resident no money was
taken, so the ledger stays consistent without a processor.

The resident portal uses Stripe.js Elements to exchange card details directly
with Stripe and sends only the resulting `pm_...` PaymentMethod ID to the API.
Each organization resolves its own Stripe credentials. Marketplace fund
routing and connected-account onboarding still require Stripe Connect and are
not provided by this payment flow.

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

### Plaid Auth and Stripe ACH setup

Both tenant integration rows must be enabled. Plaid sandbox/development may be
paired only with Stripe test keys, and Plaid production only with Stripe live
keys. Platform subscription Stripe configuration is not used and remains absent
from tenant readiness.

1. In Plaid Dashboard, enable Auth and activate the Stripe processor integration.
2. Configure tenant Plaid credentials, set `resident_ach_enabled=true`, and set
   `resident_ach_redirect_uri` when OAuth institutions require a redirect. The
   resident redirect must be registered in Plaid and is separate from the
   accounting bank-feed redirect. `resident_ach_webhook_url` is optional.
3. Configure tenant `resident_payments` with matching Stripe secret and
   publishable keys.
4. Create a Stripe webhook endpoint for
   `/api/v1/resident-payments/stripe/webhook/{webhook_key}` and subscribe to
   `charge.succeeded`, `charge.failed`, `charge.refunded`, and
   `charge.dispute.created`.
5. Save the endpoint signing secret (`whsec_...`) as the tenant
   `webhook_secret`. It is encrypted separately from the Stripe API key. The
   organization admin config response returns only masked secret hints and the
   opaque webhook route key.

Use Plaid Sandbox credentials and Stripe test keys together for testing. Use
Plaid's Auth-capable sandbox institutions and Stripe's documented ACH test
behavior. A sandbox pass does not certify live ACH origination, returns,
merchant onboarding, or NACHA compliance.

### ACH link and payment lifecycle

1. The resident accepts bank-link authorization before Plaid Link opens.
2. `POST /api/v1/resident-portal/plaid-ach/link-token` creates an Auth-only Link
   token for that resident.
3. Link returns a public token and selected opaque account ID.
   `POST /api/v1/resident-portal/plaid-ach/exchange` exchanges the public token,
   creates the Stripe `btok_...`, creates or reuses a resident-specific Stripe
   Customer, and attaches the token as a reusable `ba_...` source.
4. The Plaid Item is removed immediately in success and failure cleanup. The
   access token, Item ID, account number, routing number, credentials, and
   `btok_...` are discarded and never persisted.
5. The application retains only `cus_...`, `ba_...`, bank display name, account
   type, last four digits, method status, and consent evidence.
6. ACH initiation uses Stripe `POST /v1/charges` with the stored Customer and
   bank source. It creates a `processing` resident payment attempt but no AR
   receipt or GL entry.
7. A verified `charge.succeeded` webhook atomically posts receipts and
   `Dr Cash / Cr Accounts Receivable`. Webhook replay is a no-op.
8. Failure before settlement creates no receipt. A refund, dispute, or return
   after settlement marks the attempt returned, marks the original receipt
   reversed, and posts `Dr Accounts Receivable / Cr Cash` without deleting the
   audit history.

The webhook is primary. No polling reconciliation job is currently installed.
Operational monitoring must alert on stale `processing` attempts until a
reconciliation task is added.

### Authorization and autopay

The resident portal records the versioned bank-link authorization text,
timestamp, IP address, and user agent on the saved ACH method. Enabling ACH
autopay requires a separate recurring debit authorization and records equivalent
evidence on the lease. Property managers remain responsible for approved NACHA
authorization language, notice, revocation, retention, and return handling in
their jurisdictions and operating model.

The current application stores the autopay toggle and selected active card or
ACH method, but there is no resident autopay charging scheduler in the task
system. Do not represent the toggle as automatic monthly charging until a
scheduler is implemented using the same attempt and settlement lifecycle.

---

## Tenant screening

Organization admins configure Screening under **Finance > Connections**. The
API key is encrypted and each organization has independent URLs and polling
limits. `SCREENING_*` remains a legacy fallback only when no tenant row exists.

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

Organization admins configure Plaid under **Finance > Connections**. Link,
token exchange, account lookup, interactive sync, and background sync resolve
the connection organization's encrypted tenant credentials. `PLAID_*` remains
a legacy fallback only when no tenant row exists.

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

### Applicant financial verification

Applicant financial verification is a separate consent-gated workflow attached
to a rental application. It does not use `BankFeedConnection` or
`ScreeningReport`. Enable it per organization in **Finance > Connections >
Plaid** after tenant Plaid credentials are saved.

The staff workflow sends a seven-day magic link. The invitation token is stored
only as a SHA-256 hash. The browser exchanges the URL token for a scoped,
httpOnly, SameSite cookie and removes the token from browser history. Before
Plaid Link opens, the applicant sees the requesting organization, application
context, exact checks, retention summary, and an explicit consent checkbox. A
link token cannot be created before consent is recorded.

Implemented Plaid products and calls:

| Purpose | Link product or endpoint | Retained result |
|---|---|---|
| Identity and owner match | `identity`, then `/identity/get` | Match boolean and normalized score only |
| Account ownership usability | `auth`, then `/auth/get` | Whether usable auth data exists and aggregate usable account count |
| Real-time balances | `/accounts/balance/get` | Aggregate current and available totals plus account count |
| Recent recurring income estimate | `transactions`, then bounded `/transactions/get` for up to 90 days | Monthly estimate, months observed, methodology version, and reason codes |

`balance` is an endpoint, not a Link product. Auth account and routing numbers
are used only in memory to establish that selected accounts are usable. Raw
owner identity, addresses, account numbers, routing numbers, account-level
balances, masks, transaction rows, and transaction descriptions are discarded.
Plaid credentials are never visible to Portfolio Desk or the requesting
organization.

The recommendation is limited to `verified`, `review`, or `insufficient` with
reason codes. It is decision support only. The workflow does not automatically
approve, deny, or generate adverse action, and it is not a consumer report or
background screening product. Staff must evaluate results under their own
documented rental criteria and applicable law. Aggregate balances alone must
not determine a rental decision.

Identity, auth, and balance checks run immediately after Link. If Transactions
returns `PRODUCT_NOT_READY`, the request remains in `processing` with only the
encrypted access token and the already-minimized partial summary. A verified
`INITIAL_UPDATE` or `SYNC_UPDATES_AVAILABLE` webhook resumes the bounded
transaction check. After completion or terminal failure, the service calls
`/item/remove` and clears the encrypted access token. Only the minimized summary
remains. This short processing window also limits webhook exposure.

### Applicant webhook setup

Set the tenant Plaid applicant webhook URL to:

```text
https://api.example.com/api/v1/leasing-funnel/plaid/webhook
```

For the current development application host, use:

```text
https://dev.app.portfoliodesk.ai/api/v1/leasing-funnel/plaid/webhook
```

The frontend host proxies `/api/` to the backend, so a separate API hostname is
not required. The URL must remain publicly reachable over HTTPS for Plaid.

For OAuth institutions, add this applicant redirect URI to the Plaid dashboard's
allowed redirect URIs, then save the same value in the tenant Plaid form:

```text
https://dev.app.portfoliodesk.ai/financial-verify
```

This is separate from the accounting bank-feed redirect URI. Applicant Link
uses the public verification page so OAuth users return to their scoped,
cookie-backed verification session instead of the authenticated Finance page.
Leave the applicant redirect field blank when testing non-OAuth Sandbox
institutions. Sending an unregistered redirect causes Plaid `INVALID_FIELD` and
prevents Link from opening.

The endpoint maps `item_id` to an organization under a narrow trusted RLS
bypass, switches to that tenant, retrieves Plaid's verification key, verifies
the ES256 `X-Plaid-Verification` JWT and exact request-body SHA-256 claim, and
deduplicates by event digest. Unsigned or invalid webhooks are rejected. Known
permission revocations mark the request revoked. Login and Item errors mark it
action required. Unsupported metadata is logged without tokens or financial
payload content.

Because Items are removed immediately after successful processing, revocation
webhooks normally matter only during the linking and short asynchronous
processing window.

### Applicant sandbox certification checklist

1. Enable Identity, Auth, and Transactions for the Plaid Sandbox team and app.
2. Register the exact redirect URI for OAuth institutions and the HTTPS webhook
   URL shown above.
3. Enable applicant financial verification in the tenant Plaid form.
4. Send a request to a synthetic submitted application and confirm no link token
   is returned before consent.
5. Complete Sandbox Link with Plaid test users for a successful Item, an auth
   data unavailable case, and an Item login error.
6. Confirm only hashes, consent evidence, aggregate metrics, match flags,
   methodology, and reason codes exist in PostgreSQL and API responses.
7. Search application and provider logs for the test token, access token,
   account and routing numbers, owner payload, and transaction descriptions.
   All searches must be empty.
8. Replay a signed webhook and confirm idempotency. Alter one body byte and
   confirm signature rejection.
9. Simulate `PRODUCT_NOT_READY`, then send a signed `INITIAL_UPDATE` webhook and
   confirm processing resumes exactly once.
10. Confirm `/item/remove` succeeds and `access_token_encrypted` is cleared after
   completion.
11. Record Plaid product approval, webhook test evidence, operator, timestamp,
    and build SHA. Sandbox success does not certify Production access.

Plaid Assets and Payroll Income are not implemented. They require separate
product approval and asynchronous or product-specific API flows. Do not present
either capability to applicants or staff until those flows are designed,
approved, and certified.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Connect raises about `ENCRYPTION_KEY` | Key unset and `APP_ENV` is not a dev value. Working as designed. |
| Intuit rejects the redirect | `QBO_REDIRECT_URI` differs from the app registration, including trailing slash |
| QuickBooks sync skips everything | Accounts unmapped. Pull the chart of accounts and map them. |
| Small banks connect, Chase fails | `PLAID_REDIRECT_URI` unset or not registered with Plaid |
| Payment reports `unconfigured` | Resident Payments is not configured or enabled for the organization. Configure it under Accounting connections. Payment is recorded as pending and no money is taken. |
| Screening always says "review" | Screening is not configured or enabled for the organization. Configure it under Accounting connections. |
| SSO callback returns `verification_failed` | Check `aud` matches the client ID, `iss` matches the configured issuer, and the email domain is allowed |

See also [MIGRATIONS.md](MIGRATIONS.md). Tenant provider settings require
revision 120 and applicant financial verification requires revision 121. Existing deployments can continue using environment fallback
while each organization saves its own encrypted configuration.

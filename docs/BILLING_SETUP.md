# Stripe Billing Setup

Portfolio Desk standard billing is monthly and usage-based:

```text
Monthly charge = $39 + ($4 x max(monthly active leases - 3, 0))
```

The Base subscription includes every non-Enterprise application feature. Enterprise remains a custom plan with a separately provisioned Stripe Price and activation-code workflow.

## What Counts as an Active Lease

A commercial or residential lease counts once for a UTC calendar month when its saved status is exactly `Active` for at least one day in that month.

Portfolio Desk writes an immutable `active_lease_months` row when a lease is saved as Active. Leases that remain Active across a month boundary are carried into the new month automatically. Changing or deleting the lease later does not reduce the completed month's usage.

Self-storage agreements do not count as leases under this billing rule.

## Create the Standard Stripe Price

In Stripe, create one recurring monthly Price under the Base product:

- Pricing model: **Graduated tiers**
- Billing period: **Monthly**
- Usage type: **Licensed**
- Currency: **USD**

Configure the tiers:

| Tier | Up to | Unit amount | Flat amount |
| --- | ---: | ---: | ---: |
| Included leases | 3 | $0.00 | $39.00 |
| Additional leases | Infinity | $4.00 | $0.00 |

Examples:

| Monthly-active leases | Stripe quantity | Charge |
| ---: | ---: | ---: |
| 0 | 3 | $39 |
| 1 | 3 | $39 |
| 3 | 3 | $39 |
| 4 | 4 | $43 |
| 10 | 10 | $67 |

Portfolio Desk reports at least quantity 3 so the flat first tier is always charged. Store this Price ID in `STRIPE_PRICE_ID_PRO`; the internal `pro` identifier now represents the full-feature Base subscription.

```dotenv
STRIPE_PRICE_ID_PRO=price_...
```

Legacy Starter and annual Price fields remain in the schema for deployment compatibility but are not used by new standard checkout.

## Enterprise

Create one Enterprise Product and provision customer-specific recurring Prices beneath it. Configure:

```dotenv
STRIPE_PRODUCT_ID_ENTERPRISE=prod_...
```

Use the platform billing console to mint an Enterprise activation code linked to the customer's bespoke Stripe Price. Enterprise subscriptions do not receive standard active-lease quantity updates.

## Discount Codes

The platform billing console can issue Stripe-backed promotion codes.

Supported code shapes:

- **One invoice, one use:** set duration to `once` and maximum redemptions to `1`.
- **Term percentage:** set a percentage and duration to a fixed number of months.
- **Term fixed amount:** set a USD amount and duration to a fixed number of months.
- **Multi-use campaigns:** increase maximum redemptions when explicitly intended.

Customers enter codes in Stripe Checkout. Stripe enforces expiration, duration, and maximum redemptions. Portfolio Desk stores the Stripe coupon and promotion-code identifiers and records completed Checkout redemptions by organization.

Deactivating a code in Portfolio Desk disables the Stripe Promotion Code. It does not remove a discount already attached to an active subscription.

## Webhook

Configure the webhook endpoint:

```text
https://YOUR_APP_HOST/api/v1/billing/webhooks
```

At minimum subscribe to:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.created`
- `invoice.finalized`
- `invoice.paid`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `charge.succeeded`
- `charge.failed`
- `charge.refunded`
- `charge.updated`
- `refund.created`
- `refund.updated`
- `coupon.created`
- `coupon.updated`
- `coupon.deleted`

Configure the signing secret as `STRIPE_WEBHOOK_SECRET`.

## Deployment

Required standard settings:

```dotenv
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PRICE_ID_PRO=price_...
STRIPE_PRODUCT_ID_ENTERPRISE=prod_...
```

The platform admin console may store Stripe settings in the database. Enabled database settings override environment fallbacks. Stored secrets require `ENCRYPTION_KEY`.

Apply migration `116_active_lease_billing_and_discounts.py` before deploying the new application version. The migration backfills exact Active commercial and residential leases into the current month.

## Operational Checks

After deployment:

1. Verify the Stripe configuration through the platform billing console.
2. Save test leases as Active and run **Sync usage** on the customer Billing page.
3. Confirm the displayed monthly-active, included, and billed lease counts.
4. Confirm Stripe subscription quantity is at least 3 and matches total monthly-active leases above 3.
5. Complete a test Checkout with a one-use code.
6. Confirm the code redemption count increments in the platform billing console.
7. Verify Enterprise subscriptions do not change quantity during standard usage sync.

# Sample data for testing AI lease ingestion

`sample_commercial_lease.pdf` is a short, realistic commercial office lease you
can upload to exercise the AI lease parser.

## How to use it

1. Go to **Leases → New lease** (the AI panel only shows when *creating* a
   lease, not editing).
2. In **"AI assist — extract from document"**, choose
   `sample_commercial_lease.pdf` and click **Extract details**.
3. The form fields below are pre-filled with the model's suggestions for you to
   review and save.

> Requires a `GEMINI_API_KEY` configured on the backend. Without it the endpoint
> returns `503` and the panel shows "AI assist is not configured on the server."

## What the document contains

The lease text intentionally includes every field that
`parse_lease_document` extracts (`backend/app/services/ai_service.py`):

| Field | Value in the sample |
| --- | --- |
| `lease_name` | Northwind Analytics – Suite 1200 |
| `lessor_name` | Greenfield Property Holdings, LLC |
| `lease_commencement_date` | 2025-01-01 |
| `lease_expiration` | 2029-12-31 |
| `lease_notice_date` | 2029-10-02 |
| `notice_period` | 90 days |
| `notice_period_days` | 90 |
| `payment_amount` | 28500.00 |
| `payment_frequency` | monthly |
| `annual_escalation_rate` | 0.03 |
| `expiration_year` | 2029 |

## Regenerating the PDF

The PDF is produced by `generate_sample_lease.py` (uses `reportlab`, which is
**not** a project dependency — install it just to regenerate):

```bash
pip install reportlab
python docs/samples/generate_sample_lease.py
```

## Full Lease Abstract sample

`sample_full_abstract_lease.pdf` is a longer lease whose articles map 1:1 onto
**every** category in the Lease Abstract catalog
(`backend/app/services/lease_abstract_catalog.py`, 35 categories). Use it on a
lease's **Abstract** screen ("Suggest with AI") so
`POST /api/v1/ai/leases/{id}/abstract/suggest` can populate all clause
categories — not just the headline fields covered by
`sample_commercial_lease.pdf`.

Each article spells out the concrete figures behind the structured fields a
category captures (square footage, dates, dollar amounts, percentages, notice
periods, caps, etc.) so the extraction has real content to summarise for every
category.

Regenerate it the same way (it imports the catalog from the backend package, so
it stays in lock-step with the canonical category list):

```bash
pip install reportlab
python docs/samples/generate_full_abstract_lease.py
```


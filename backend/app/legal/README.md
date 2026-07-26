# Legal documents

This directory holds the platform's legal documents (Terms of Service, EULA,
Privacy Policy, Acceptable Use Policy, ...). They are the single source of truth
consumed by:

- the backend public API (`GET /api/v1/legal`, `GET /api/v1/legal/{slug}`),
- the web app signup flow and public legal viewer (`/legal`),
- the marketing/landing site footer (which links to the app viewer).

## Editing without a code change

The document text lives in plain Markdown files under `documents/`. To update a
document, **edit its Markdown file** — no code changes are required. The API
renders the Markdown to HTML at request time, so the new text is served as soon
as the file is deployed.

## Adding, removing, or versioning a document

`manifest.json` is the index. Each entry has:

| field              | meaning                                                        |
| ------------------ | ------------------------------------------------------------- |
| `slug`             | URL-safe id used in API paths and app routes (`/legal/{slug}`) |
| `title`            | Display title                                                 |
| `version`          | Version string recorded when a user accepts the document      |
| `effective_date`   | Date the version takes effect                                 |
| `summary`          | Short description shown in listings                           |
| `required_at_signup` | Whether the document must be accepted to create an org      |
| `file`             | Markdown filename inside `documents/`                          |

When you materially change a document, **bump its `version`** so acceptances are
recorded against the new version.

> These documents are provided as starting templates and should be reviewed by
> qualified legal counsel before production use.

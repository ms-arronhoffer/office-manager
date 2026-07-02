# Portfolio Desk — Marketing Site

A fast, static marketing site built with [Astro](https://astro.build) and Tailwind CSS,
served by nginx in production (see `Dockerfile` / `nginx.conf`).

## Develop

```bash
npm install --legacy-peer-deps
npm run dev      # local dev server
npm run build    # static build into dist/
npm run preview  # preview the production build
```

## Pages

The site is multi-page. Routes live in `src/pages/`:

| Route | Source |
| --- | --- |
| `/` | `index.astro` — home (hero, showcase, features, pricing, tutorials teaser) |
| `/features` | `features.astro` — feature deep-dive with product screenshots |
| `/pricing` | `pricing.astro` — plans + pricing FAQ |
| `/tutorials` | `tutorials/index.astro` — tutorial index |
| `/tutorials/<slug>` | `tutorials/[slug].astro` — generated from `src/config/tutorialContent.ts` |
| `/contact` | `contact.astro` — spam-resistant contact form |

## Runtime configuration (`public/config.js`)

Deployment URLs and contact settings are read at runtime from `public/config.js`,
so the same image works across environments with no rebuild. Edit that file to point
at your deployment:

- `APP_URL`, `SIGNUP_URL`, `LOGIN_URL` — wired into every `[data-href]` CTA.
- `CONTACT_ENDPOINT` — optional. When set, the contact form `POST`s JSON
  (`name`, `company`, `email`, `topic`, `message`) to this URL (e.g. a serverless
  function or form backend). When blank, the form falls back to a JS-built email
  draft using `SUPPORT_EMAIL`.
- `COMPANY_NAME` — fills every `[data-company]` wordmark.

### Spam-resistant contact

The site intentionally contains **no clickable email address** in its HTML —
publishing one only feeds spam harvesters. Instead, `/contact` uses a form
(`src/components/ContactForm.astro`) protected by:

1. A destination address assembled at runtime from `config.js` (never in the page source).
2. A hidden honeypot field that silently drops bot submissions.
3. A time-to-submit heuristic that rejects instant (bot) submissions.

## Product screenshots

The "screenshots" under `src/components/screens/` are high-fidelity, responsive
recreations of the real product UI (built with the same design language), wrapped
in `AppShell.astro`. They render crisply at any size and stay in sync with the
brand without shipping heavy binary images.

## Add a tutorial

1. Add an entry to `tutorials` in `src/config/site.ts` (slug, title, summary, level, minutes, topics).
2. Add the matching body to `tutorialContent` in `src/config/tutorialContent.ts`.

The new page is generated automatically and linked from the index and home teaser.

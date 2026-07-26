// Landing page runtime configuration.
// Edit these URLs to point at your deployment, no image rebuild required.
window.SITE_CONFIG = {
  APP_URL:       "https://app.portfoliodesk.ai",
  SIGNUP_URL:    "https://app.portfoliodesk.ai/signup",
  LOGIN_URL:     "https://app.portfoliodesk.ai/login",
  MANAGE_URL:    "https://manage.portfoliodesk.ai",

  // Legal documents. These point at the app's public legal viewer, which is the
  // single source of truth (rendered from Markdown on the backend), so the
  // documents can be updated without rebuilding the landing site.
  LEGAL_URL:     "https://app.portfoliodesk.ai/legal",
  TERMS_URL:     "https://app.portfoliodesk.ai/legal/terms-of-service",
  EULA_URL:      "https://app.portfoliodesk.ai/legal/eula",
  PRIVACY_URL:   "https://app.portfoliodesk.ai/legal/privacy-policy",
  AUP_URL:       "https://app.portfoliodesk.ai/legal/acceptable-use-policy",

  // Contact handling. The on-site /contact form posts JSON to CONTACT_ENDPOINT
  // (e.g. a serverless function or form backend). When left blank, the form
  // falls back to a JS-built mailto using SUPPORT_EMAIL, assembled at submit
  // time so the address is NEVER present in the static HTML for spam harvesters.
  CONTACT_ENDPOINT: "",
  DEMO_EMAIL:    "demo@yourcompany.com",
  SUPPORT_EMAIL: "support@yourcompany.com",

  COMPANY_NAME:  "Portfolio Desk",
  TAGLINE:       "Every office. Every lease. Every deadline. One platform.",
};

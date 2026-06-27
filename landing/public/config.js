// Landing page runtime configuration.
// Edit these URLs to point at your deployment — no image rebuild required.
window.SITE_CONFIG = {
  APP_URL:       "https://dev.officemanager.techtools.host",
  SIGNUP_URL:    "https://dev.officemanager.techtools.host/signup",
  LOGIN_URL:     "https://dev.officemanager.techtools.host/login",

  // Contact handling. The on-site /contact form posts JSON to CONTACT_ENDPOINT
  // (e.g. a serverless function or form backend). When left blank, the form
  // falls back to a JS-built mailto using SUPPORT_EMAIL — assembled at submit
  // time so the address is NEVER present in the static HTML for spam harvesters.
  CONTACT_ENDPOINT: "",
  DEMO_EMAIL:    "demo@yourcompany.com",
  SUPPORT_EMAIL: "support@yourcompany.com",

  COMPANY_NAME:  "SwiftLease",
  TAGLINE:       "Every office. Every lease. Every deadline. One platform.",
};

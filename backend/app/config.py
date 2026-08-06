from urllib.parse import quote_plus
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database — built from components to handle special chars in password
    POSTGRES_USER: str = "office_admin"
    POSTGRES_PASSWORD: str
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "office_manager"
    # These can still be set directly as env vars to override the computed URLs
    DATABASE_URL: str = ""
    DATABASE_URL_SYNC: str = ""

    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRY_HOURS: int = 8
    JWT_ACCESS_MINUTES: int = 30
    # Defense-in-depth: when true, every authenticated request sets the
    # Postgres session GUC `app.current_org` so that Row-Level Security
    # policies (see docs/RLS_EVALUATION.md) fail closed even if an app-level
    # org filter is ever missed. Production Compose enables this after startup
    # applies migration 118; local development remains opt-in.
    RLS_BACKSTOP_ENABLED: bool = False
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@officemanager.local"
    # Optional per-category From addresses. When set, outbound mail uses the
    # matching address based on its purpose so system messages, user
    # notifications, and waiver invitations can come from distinct mailboxes.
    # Any left blank fall back to SMTP_FROM. See app.utils.email_client.
    SMTP_FROM_SYSTEM: str = ""
    SMTP_FROM_NOTIFICATIONS: str = ""
    SMTP_FROM_WAIVERS: str = ""
    # Address that receives in-app support requests (see app.routers.support_requests).
    # Configured via the environment rather than admin UI so it can't be changed
    # per-tenant or without deploy access.
    SUPPORT_EMAIL: str = ""
    # SMS / text-message provider (Twilio-style). Optional; when unset the SMS
    # channel degrades to a logged no-op (see app.utils.sms_client).
    SMS_ACCOUNT_SID: str = ""
    SMS_AUTH_TOKEN: str = ""
    SMS_FROM: str = ""
    # Legacy bootstrap fallback for tenant payment configuration. Tenant rows
    # configured in Finance > Connections take precedence for runtime traffic.
    PAYMENTS_PROVIDER: str = "stripe"
    PAYMENTS_API_KEY: str = ""
    PAYMENTS_PUBLISHABLE_KEY: str = ""
    PAYMENTS_API_URL: str = ""
    # Legacy bootstrap fallback for tenant screening configuration. New
    # production tenants should configure this in Finance > Connections.
    SCREENING_PROVIDER: str = "transunion"
    SCREENING_API_KEY: str = ""
    SCREENING_API_URL: str = ""
    # Optional provider-documented, non-mutating health/authentication endpoint.
    # Readiness verification is disabled when this is blank.
    SCREENING_HEALTH_URL: str = ""
    # How long to wait for a provider that answers asynchronously before leaving
    # the report 'pending' for a later refresh.
    SCREENING_POLL_ATTEMPTS: int = 5
    SCREENING_POLL_INTERVAL_SECONDS: float = 2.0
    FRONTEND_URL: str = "http://localhost:3000"
    ADMIN_FRONTEND_URL: str = "http://localhost:4001"
    DEFAULT_ADMIN_EMAIL: str = "admin@officemanager.local"
    DEFAULT_ADMIN_PASSWORD: str
    # Comma-separated list of emails to promote to platform super-admin on every
    # container start. Useful for healing access in an existing database without
    # console access. Matching is case-insensitive; missing users are skipped.
    SUPER_ADMIN_EMAILS: str = ""

    # File uploads
    UPLOAD_DIR: str = "/app/uploads"
    MAX_FILE_SIZE_MB: int = 75
    # Documents handed to the AI assistant are processed in-memory (extracted,
    # segmented, sent to Gemini) rather than stored, so they get their own
    # ceiling, independent of stored attachments. Keep any reverse proxy's
    # ``client_max_body_size`` at or above both values.
    AI_MAX_FILE_SIZE_MB: int = 75
    ALLOWED_EXTENSIONS: str = ".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.tif,.tiff,.txt"
    # Storage backend for uploaded files: "local" (default, UPLOAD_DIR on disk;
    # single-VPS docker-compose deploy) or "s3" (required once more than one
    # backend replica/AZ is in play — see app.utils.file_storage and
    # docs/aws-deployment.md).
    STORAGE_BACKEND: str = "local"
    S3_UPLOAD_BUCKET: str = ""
    S3_UPLOAD_PREFIX: str = "uploads"
    AWS_REGION: str = "us-east-2"

    # Stripe billing
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_STARTER: str = ""
    STRIPE_PRICE_ID_PRO: str = ""
    STRIPE_PRICE_ID_STARTER_ANNUAL: str = ""
    STRIPE_PRICE_ID_PRO_ANNUAL: str = ""
    # Enterprise is custom-priced per subscriber, so there is no shared price id.
    # Instead we identify Enterprise subscriptions by their Stripe Product, under
    # which each subscriber's bespoke price is created.
    STRIPE_PRODUCT_ID_ENTERPRISE: str = ""

    # Trial period
    TRIAL_DAYS: int = 14

    # ── Observability ────────────────────────────────────────────────────
    # Deployment environment label (e.g. "production", "staging", "dev").
    # Used to tag logs and Sentry events.
    APP_ENV: str = "development"
    # Root log level: DEBUG / INFO / WARNING / ERROR.
    LOG_LEVEL: str = "INFO"
    # Log output format: "json" for structured logs (recommended in prod) or
    # "plain" for human-readable console output.
    LOG_FORMAT: str = "plain"
    # Error tracking. When SENTRY_DSN is empty, Sentry is disabled and the app
    # degrades gracefully (mirroring SMTP/Stripe/Gemini optional integrations).
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0

    # Slack webhook for internal ops alerts (billing events, etc.). Optional.
    SLACK_WEBHOOK_URL: str = ""

    # AI provider selection. Leave AI_PROVIDER empty to preserve the legacy
    # behaviour of selecting Gemini whenever GEMINI_API_KEY is configured.
    AI_PROVIDER: str = ""
    AI_MODEL: str = ""
    AI_MODEL_FAST: str = ""
    AI_EMBED_PROVIDER: str = ""
    AI_EMBED_MODEL: str = ""
    # The pgvector columns and indexes use vector(768). Providers that support
    # configurable embedding widths must be asked for this exact dimension.
    AI_EMBED_DIMENSIONS: int = 768
    AI_TIMEOUT_SECONDS: int = 60
    AI_MAX_RETRIES: int = 2
    AI_RETRY_BASE_SECONDS: float = 0.5

    # Google Gemini (AI assist). All three are configurable so the model id and
    # endpoint can be corrected without a code change. When GEMINI_API_KEY is
    # empty the AI features degrade gracefully (mirroring SMTP/Stripe).
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    # Optional cheaper/faster model for low-stakes tasks (e.g. intent parsing).
    # Falls back to GEMINI_MODEL when left empty so behaviour is unchanged unless
    # explicitly configured.
    GEMINI_MODEL_FAST: str = ""
    GEMINI_EMBED_MODEL: str = "gemini-embedding-001"
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_TIMEOUT_SECONDS: int = 60
    # Bounded retry for transient upstream failures (429 / 5xx / network) on
    # idempotent generate + embed calls. Set MAX_RETRIES=0 to disable.
    GEMINI_MAX_RETRIES: int = 2
    GEMINI_RETRY_BASE_SECONDS: float = 0.5

    # OpenAI generation and embeddings. OPENAI_API_BASE can point at an
    # OpenAI-compatible gateway when required.
    OPENAI_API_KEY: str = ""
    OPENAI_API_BASE: str = "https://api.openai.com/v1"

    # OpenRouter uses the OpenAI-compatible chat-completions protocol. The
    # optional site URL and app name are sent as OpenRouter attribution headers.
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_API_BASE: str = "https://openrouter.ai/api/v1"
    OPENROUTER_SITE_URL: str = ""
    OPENROUTER_APP_NAME: str = "Portfolio Desk"

    # Symmetric encryption key (urlsafe-base64, 32 bytes — see
    # ``Fernet.generate_key()``) used to encrypt third-party secrets we must
    # store and later send back out verbatim (e.g. the Buildium API client
    # secret). See app.utils.crypto. Optional in dev; required in production.
    ENCRYPTION_KEY: str = ""

    # Absolute URL of the OIDC redirect endpoint (app.routers.sso.callback).
    # Must match the redirect URI registered with each customer's identity
    # provider, so it is configured rather than derived from the request.
    SSO_CALLBACK_URL: str = "http://localhost:8000/api/v1/sso/callback"

    # Buildium Open API connector (see app.services.buildium).
    BUILDIUM_API_BASE_URL: str = "https://api.buildium.com/v1"
    BUILDIUM_TIMEOUT_SECONDS: int = 60
    BUILDIUM_MAX_RETRIES: int = 4
    BUILDIUM_RETRY_BASE_SECONDS: float = 1.0
    BUILDIUM_PAGE_SIZE: int = 100

    # QuickBooks Online two-way sync (see app.services.quickbooks). Optional;
    # when QBO_CLIENT_ID/QBO_CLIENT_SECRET are empty the connector reports
    # itself unconfigured instead of failing (mirroring SMTP/Stripe/Plaid).
    QBO_CLIENT_ID: str = ""
    QBO_CLIENT_SECRET: str = ""
    # Must exactly match the redirect URI registered on the Intuit app.
    QBO_REDIRECT_URI: str = ""
    QBO_ENVIRONMENT: str = "production"
    QBO_API_BASE_URL: str = "https://quickbooks.api.intuit.com/v3/company"
    QBO_AUTH_URL: str = "https://appcenter.intuit.com/connect/oauth2"
    QBO_TOKEN_URL: str = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
    QBO_MINOR_VERSION: str = "70"
    QBO_TIMEOUT_SECONDS: int = 30
    QBO_MAX_RETRIES: int = 3
    QBO_RETRY_BASE_SECONDS: float = 1.0
    # Refresh the access token this many seconds before it actually expires so a
    # long-running push doesn't die mid-batch.
    QBO_TOKEN_REFRESH_LEEWAY_SECONDS: int = 300
    # Upper bound on journal entries pushed in a single sync run.
    QBO_PUSH_BATCH_LIMIT: int = 200

    # Legacy bootstrap fallback for Plaid. Tenant rows configured in Finance >
    # Connections take precedence, including in background connection syncs.
    PLAID_CLIENT_ID: str = ""
    PLAID_SECRET: str = ""
    PLAID_ENV: str = "production"
    PLAID_API_BASE_URL: str = "https://production.plaid.com"
    PLAID_TIMEOUT_SECONDS: int = 30
    PLAID_COUNTRY_CODES: str = "US"
    PLAID_REDIRECT_URI: str = ""
    # Max /transactions/sync pages walked per run, bounding a first-time backfill.
    PLAID_MAX_SYNC_PAGES: int = 20

    model_config = {"env_file": ".env", "extra": "ignore"}

    def model_post_init(self, __context) -> None:
        pw = quote_plus(self.POSTGRES_PASSWORD)
        user = quote_plus(self.POSTGRES_USER)
        base = f"{user}:{pw}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        if not self.DATABASE_URL:
            self.DATABASE_URL = f"postgresql+asyncpg://{base}"
        if not self.DATABASE_URL_SYNC:
            self.DATABASE_URL_SYNC = f"postgresql://{base}"


settings = Settings()

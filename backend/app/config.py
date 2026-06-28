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
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@officemanager.local"
    FRONTEND_URL: str = "http://localhost:3000"
    ADMIN_FRONTEND_URL: str = "http://localhost:4001"
    DEFAULT_ADMIN_EMAIL: str = "admin@officemanager.local"
    DEFAULT_ADMIN_PASSWORD: str

    # File uploads
    UPLOAD_DIR: str = "/app/uploads"
    MAX_FILE_SIZE_MB: int = 25
    ALLOWED_EXTENSIONS: str = ".pdf,.doc,.docx,.xls,.xlsx,.csv,.png,.jpg,.jpeg,.tif,.tiff,.txt"

    # Stripe billing
    STRIPE_SECRET_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""
    STRIPE_PRICE_ID_PRO: str = ""
    STRIPE_PRICE_ID_ENTERPRISE: str = ""

    # Trial period
    TRIAL_DAYS: int = 30

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

    # Google Gemini (AI assist). All three are configurable so the model id and
    # endpoint can be corrected without a code change. When GEMINI_API_KEY is
    # empty the AI features degrade gracefully (mirroring SMTP/Stripe).
    GEMINI_API_KEY: str = ""
    GEMINI_MODEL: str = "gemini-3.1-flash-lite"
    GEMINI_EMBED_MODEL: str = "text-embedding-004"
    GEMINI_API_BASE: str = "https://generativelanguage.googleapis.com/v1beta"
    GEMINI_TIMEOUT_SECONDS: int = 60

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

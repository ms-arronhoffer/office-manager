# A single JSON secret holds every app secret so start.py/docker-compose can
# fetch them with one API call. The EC2 instance role is granted read-only
# access (see ec2.tf); nothing else can read it.

resource "aws_secretsmanager_secret" "app" {
  name        = "${var.project_name}/${var.environment}/app-secrets"
  description = "Office Manager application secrets (DB password, JWT secret, third-party API keys)."
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    # Use the same trimmed password RDS is created with (see rds.tf) so the
    # app's stored credential always matches the actual DB master password.
    POSTGRES_PASSWORD      = trimspace(var.db_password)
    JWT_SECRET             = var.jwt_secret
    DEFAULT_ADMIN_PASSWORD = var.default_admin_password
    STRIPE_SECRET_KEY      = var.stripe_secret_key
    GEMINI_API_KEY         = var.gemini_api_key
    SENTRY_DSN             = var.sentry_dsn
    # Folded in so the SSM-driven deploy can build the whole container .env
    # on-box from this single secret (see .github/workflows/infra-prod.yml).
    GOOGLE_CLIENT_SECRET = var.google_client_secret
    SMTP_USER            = var.smtp_user
    SMTP_PASSWORD        = var.smtp_password
    NPM_ADMIN_PASSWORD   = var.npm_admin_password
  })
}

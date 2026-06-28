from pydantic import BaseModel


DEFAULT_APP_NAME = "SwiftLease"
DEFAULT_LOGIN_SUBTITLE = "Sign in to manage your offices, leases, and facilities"
DEFAULT_LOGIN_FORM_HEADER = "Sign In"
DEFAULT_LOGIN_FORM_DESCRIPTION = "Enter your credentials to access the application"
DEFAULT_SUPPORT_EMAIL = ""
DEFAULT_SLA_HIGH_DAYS = 1
DEFAULT_SLA_MEDIUM_DAYS = 3
DEFAULT_SLA_LOW_DAYS = 7


class SiteSettingsSchema(BaseModel):
    app_name: str = DEFAULT_APP_NAME
    login_subtitle: str = DEFAULT_LOGIN_SUBTITLE
    login_form_header: str = DEFAULT_LOGIN_FORM_HEADER
    login_form_description: str = DEFAULT_LOGIN_FORM_DESCRIPTION
    support_email: str = DEFAULT_SUPPORT_EMAIL
    sla_high_days: int = DEFAULT_SLA_HIGH_DAYS
    sla_medium_days: int = DEFAULT_SLA_MEDIUM_DAYS
    sla_low_days: int = DEFAULT_SLA_LOW_DAYS

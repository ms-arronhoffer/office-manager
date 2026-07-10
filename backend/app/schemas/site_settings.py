from pydantic import BaseModel


DEFAULT_COMPANY_NAME = "Portfolio Desk"
DEFAULT_COMPANY_ADDRESS = ""
DEFAULT_COMPANY_PHONE = ""
DEFAULT_COMPANY_EMAIL = ""
DEFAULT_LOGIN_SUBTITLE = "Sign in to manage your offices, leases, and facilities"
DEFAULT_LOGIN_FORM_HEADER = "Sign In"
DEFAULT_LOGIN_FORM_DESCRIPTION = "Enter your credentials to access the application"
DEFAULT_SLA_HIGH_DAYS = 1
DEFAULT_SLA_MEDIUM_DAYS = 3
DEFAULT_SLA_LOW_DAYS = 7


class SiteSettingsSchema(BaseModel):
    company_name: str = DEFAULT_COMPANY_NAME
    company_address: str = DEFAULT_COMPANY_ADDRESS
    company_phone: str = DEFAULT_COMPANY_PHONE
    company_email: str = DEFAULT_COMPANY_EMAIL
    login_subtitle: str = DEFAULT_LOGIN_SUBTITLE
    login_form_header: str = DEFAULT_LOGIN_FORM_HEADER
    login_form_description: str = DEFAULT_LOGIN_FORM_DESCRIPTION
    sla_high_days: int = DEFAULT_SLA_HIGH_DAYS
    sla_medium_days: int = DEFAULT_SLA_MEDIUM_DAYS
    sla_low_days: int = DEFAULT_SLA_LOW_DAYS

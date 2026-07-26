import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator

from app.auth.password_policy import validate_password_strength


class SignupRequest(BaseModel):
    org_name: str
    email: EmailStr
    password: str
    display_name: str
    # The signup form requires the admin to accept the legal documents (Terms of
    # Service, EULA, Privacy Policy, Acceptable Use Policy). Must be ``True``.
    accepted_legal: bool = False

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)

    @field_validator("accepted_legal")
    @classmethod
    def validate_accepted_legal(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "You must accept the Terms of Service, EULA, and Privacy Policy to continue."
            )
        return value


class SignupResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    organization: "OrganizationResponse"


class OrganizationCreate(BaseModel):
    name: str
    slug: str
    plan: str = "starter"
    max_seats: int | None = None


class OrganizationUpdate(BaseModel):
    name: str | None = None
    plan: str | None = None
    is_active: bool | None = None
    max_seats: int | None = None
    onboarding_complete: bool | None = None
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None


class OrganizationResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    plan: str
    is_active: bool
    payment_status: str = "active"
    max_seats: int | None
    onboarding_complete: bool
    stripe_customer_id: str | None = None
    stripe_subscription_id: str | None = None
    trial_ends_at: datetime | None = None
    enabled_categories: list[str] = []
    category_overrides: dict[str, bool] = {}
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

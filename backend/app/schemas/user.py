import uuid
from datetime import datetime
from pydantic import BaseModel, EmailStr, field_validator

from app.auth.password_policy import validate_password_strength


class LoginRequest(BaseModel):
    email: str
    password: str


class GoogleAuthRequest(BaseModel):
    token: str


class RegisterRequest(BaseModel):
    email: EmailStr
    display_name: str
    password: str
    role: str = "viewer"

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserInviteRequest(BaseModel):
    email: EmailStr
    display_name: str
    role: str = "viewer"


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: uuid.UUID
    organization_id: uuid.UUID | None = None
    email: str
    display_name: str
    auth_provider: str
    role: str
    is_super_admin: bool = False
    is_active: bool
    # Login remains allowed for unverified accounts so the frontend can soft-gate
    # onboarding without breaking existing auth flows.
    email_verified: bool
    last_login_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def validate_new_password(cls, value: str) -> str:
        return validate_password_strength(value)

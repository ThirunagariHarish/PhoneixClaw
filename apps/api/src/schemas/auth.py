"""
Auth request/response schemas. M1.3.
"""
from __future__ import annotations

from pydantic import BaseModel, EmailStr


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None
    invitation_code: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str
    name: str | None
    timezone: str
    is_active: bool
    is_admin: bool
    role: str
    permissions: dict
    created_at: str
    mfa_enabled: bool = False


class MFAVerifyRequest(BaseModel):
    mfa_session: str
    totp_code: str


class MFAConfirmRequest(BaseModel):
    totp_code: str

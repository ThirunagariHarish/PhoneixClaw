import io
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp
import qrcode
import qrcode.constants
from base64 import b64encode
from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError, jwt
from pydantic import BaseModel, EmailStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config.base_config import config
from shared.models.database import get_session
from shared.models.trade import User

router = APIRouter(prefix="/auth", tags=["auth"])

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://cashflowus.com")


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class MFAVerifyRequest(BaseModel):
    mfa_session: str
    totp_code: str


class MFAConfirmRequest(BaseModel):
    totp_code: str


class VerifyEmailRequest(BaseModel):
    token: str


class ResendVerificationRequest(BaseModel):
    email: EmailStr


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
    permissions: dict[str, bool]
    created_at: str
    mfa_enabled: bool = False


# ── Password helpers ────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


# ── Token helpers ───────────────────────────────────────────────────────────


def create_access_token(user_id: str, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.auth.access_token_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "access", "admin": is_admin},
        config.auth.secret_key,
        algorithm=config.auth.algorithm,
    )


def create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=config.auth.refresh_token_expire_days)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh"},
        config.auth.secret_key,
        algorithm=config.auth.algorithm,
    )


def _create_mfa_session_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "mfa_pending"},
        config.auth.secret_key,
        algorithm=config.auth.algorithm,
    )


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, config.auth.secret_key, algorithms=[config.auth.algorithm])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e


# ── Email verification helpers ──────────────────────────────────────────────


def _generate_verification_token() -> str:
    return secrets.token_urlsafe(48)


def _send_verification_email(email: str, token: str):
    from shared.email.sender import send_html_email

    link = f"{FRONTEND_URL}/verify-email?token={token}"
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 480px; margin: 0 auto; padding: 40px 20px;">
      <div style="text-align: center; margin-bottom: 32px;">
        <h1 style="color: #1a1a1a; font-size: 24px; margin: 0;">PhoenixTrade</h1>
      </div>
      <div style="background: #f8f9fa; border-radius: 12px; padding: 32px; text-align: center;">
        <h2 style="color: #1a1a1a; font-size: 20px; margin: 0 0 12px;">Verify your email</h2>
        <p style="color: #6b7280; font-size: 14px; line-height: 1.6; margin: 0 0 24px;">
          Click the button below to verify your email address and activate your account.
        </p>
        <a href="{link}"
           style="display: inline-block; background: #6366f1; color: #ffffff; text-decoration: none;
                  padding: 12px 32px; border-radius: 8px; font-weight: 600; font-size: 14px;">
          Verify Email
        </a>
        <p style="color: #9ca3af; font-size: 12px; margin-top: 24px;">
          This link expires in 24 hours. If you didn't create an account, ignore this email.
        </p>
      </div>
    </div>
    """
    send_html_email(email, "Verify your PhoenixTrade email", html)


# ── QR code helper ──────────────────────────────────────────────────────────


def _generate_qr_data_url(uri: str) -> str:
    qr = qrcode.QRCode(version=1, box_size=6, border=2, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(uri)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64}"


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if len(req.password) < 8:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Password must be at least 8 characters")

    token = _generate_verification_token()
    user = User(
        id=uuid.uuid4(),
        email=req.email,
        password_hash=hash_password(req.password),
        name=req.name,
        email_verified=False,
        email_verification_token=token,
        email_verification_expires=datetime.now(timezone.utc) + timedelta(hours=24),
    )
    session.add(user)
    await session.commit()

    _send_verification_email(req.email, token)
    return {"status": "verification_email_sent", "message": "Please check your email to verify your account."}


@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(User).where(User.email_verification_token == req.token)
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid verification token")

    if user.email_verification_expires and user.email_verification_expires < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Verification token has expired. Please request a new one.")

    user.email_verified = True
    user.email_verification_token = None
    user.email_verification_expires = None
    await session.commit()

    return {"status": "email_verified", "message": "Your email has been verified. You can now log in."}


@router.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user:
        return {"status": "ok", "message": "If that email exists, a verification email has been sent."}

    if user.email_verified:
        return {"status": "already_verified", "message": "Email is already verified."}

    token = _generate_verification_token()
    user.email_verification_token = token
    user.email_verification_expires = datetime.now(timezone.utc) + timedelta(hours=24)
    await session.commit()

    _send_verification_email(user.email, token)
    return {"status": "ok", "message": "If that email exists, a verification email has been sent."}


@router.post("/login")
async def login(req: LoginRequest, session: AsyncSession = Depends(get_session)):
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified. Please check your inbox for the verification link.",
            headers={"X-Error-Code": "EMAIL_NOT_VERIFIED"},
        )

    try:
        user.last_login = datetime.now(timezone.utc)
        await session.commit()
    except Exception:
        await session.rollback()

    user_id = str(user.id)

    if user.mfa_enabled and user.mfa_secret:
        mfa_session = _create_mfa_session_token(user_id)
        return {"requires_mfa": True, "mfa_session": mfa_session}

    return TokenResponse(
        access_token=create_access_token(user_id, is_admin=user.is_admin),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/mfa/verify", response_model=TokenResponse)
async def mfa_verify(req: MFAVerifyRequest, session: AsyncSession = Depends(get_session)):
    payload = decode_token(req.mfa_session)
    if payload.get("type") != "mfa_pending":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA session")

    user_id = payload["sub"]
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(req.totp_code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authentication code")

    return TokenResponse(
        access_token=create_access_token(user_id, is_admin=user.is_admin),
        refresh_token=create_refresh_token(user_id),
    )


@router.post("/mfa/setup")
async def mfa_setup(request: Request, session: AsyncSession = Depends(get_session)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")

    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(name=user.email, issuer_name="PhoenixTrade")
    qr_data_url = _generate_qr_data_url(provisioning_uri)

    user.mfa_secret = secret
    await session.commit()

    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri,
        "qr_code": qr_data_url,
    }


@router.post("/mfa/confirm")
async def mfa_confirm(request: Request, req: MFAConfirmRequest, session: AsyncSession = Depends(get_session)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA is already enabled")

    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call /mfa/setup first")

    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(req.totp_code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code. Please try again.")

    user.mfa_enabled = True
    await session.commit()

    return {"status": "mfa_enabled", "message": "Two-factor authentication has been enabled."}


@router.post("/mfa/disable")
async def mfa_disable(request: Request, session: AsyncSession = Depends(get_session)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.mfa_secret = None
    user.mfa_enabled = False
    await session.commit()

    return {"status": "mfa_disabled", "message": "Two-factor authentication has been disabled."}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, session: AsyncSession = Depends(get_session)):
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")
    user_id = payload["sub"]
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return TokenResponse(
        access_token=create_access_token(user_id, is_admin=user.is_admin),
        refresh_token=create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, session: AsyncSession = Depends(get_session)):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    from shared.models.trade import ADMIN_PERMISSIONS, DEFAULT_PERMISSIONS
    perms = ADMIN_PERMISSIONS if user.is_admin else (getattr(user, "permissions", None) or DEFAULT_PERMISSIONS)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        timezone=user.timezone,
        is_active=user.is_active,
        is_admin=user.is_admin,
        role=getattr(user, "role", "trader") or "trader",
        permissions=perms,
        created_at=user.created_at.isoformat(),
        mfa_enabled=user.mfa_enabled,
    )

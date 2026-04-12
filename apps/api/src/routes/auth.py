"""
Auth routes: register, login, refresh, me, MFA. M1.3.
"""

import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import pyotp
from fastapi import APIRouter, HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select

from apps.api.src.config import auth_settings
from apps.api.src.deps import DbSession
from apps.api.src.schemas.auth import (
    LoginRequest,
    MFAConfirmRequest,
    MFAVerifyRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from shared.db.models.invitation import Invitation
from shared.db.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

# Default permissions (PRD 3.9). Admin gets all.
DEFAULT_PERMISSIONS = {"agents:read": True, "trades:read": True, "positions:read": True}
ADMIN_PERMISSIONS = {f"{r}:{a}": True for r in ["agents", "trades", "positions", "admin"] for a in ["read", "write"]}


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


def _create_access_token(user_id: str, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=auth_settings.jwt_access_token_expire_minutes)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "access", "admin": is_admin},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )


def _create_refresh_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=auth_settings.jwt_refresh_token_expire_days)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "refresh"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )


def _create_mfa_session_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "mfa_pending"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )


def _decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            auth_settings.jwt_secret_key,
            algorithms=[auth_settings.jwt_algorithm],
        )
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, session: DbSession):
    # --- Invitation validation (BEFORE email check to prevent enumeration) ---
    bootstrap_code = auth_settings.phoenix_admin_invite_code
    is_bootstrap = bool(bootstrap_code) and req.invitation_code == bootstrap_code
    invitation = None

    if not is_bootstrap:
        # Look up the invitation code in the DB
        inv_result = await session.execute(
            select(Invitation).where(Invitation.code == req.invitation_code, Invitation.used_by.is_(None))
        )
        invitation = inv_result.scalar_one_or_none()
        if not invitation:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid or already-used invitation code",
            )
        if invitation.expires_at and invitation.expires_at < datetime.now(timezone.utc):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invitation code has expired",
            )

    # --- Now check email uniqueness ---
    result = await session.execute(select(User).where(User.email == req.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if len(req.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    user = User(
        id=uuid.uuid4(),
        email=req.email,
        hashed_password=_hash_password(req.password),
        name=req.name,
        email_verified=True,
        is_admin=is_bootstrap,
        role="admin" if is_bootstrap else "trader",
        permissions=ADMIN_PERMISSIONS if is_bootstrap else DEFAULT_PERMISSIONS,
    )
    session.add(user)

    # Mark invitation as used in the same transaction
    if invitation:
        invitation.used_by = user.id
        invitation.used_at = datetime.now(timezone.utc)

    await session.commit()
    return {"status": "created", "message": "Account created. You can log in."}


@router.post("/login")
async def login(req: LoginRequest, session: DbSession):
    result = await session.execute(select(User).where(User.email == req.email))
    user = result.scalar_one_or_none()
    if not user or not _verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not getattr(user, "email_verified", True):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email not verified",
            headers={"X-Error-Code": "EMAIL_NOT_VERIFIED"},
        )
    user.last_login = datetime.now(timezone.utc)
    await session.commit()
    user_id = str(user.id)
    if user.mfa_enabled and user.mfa_secret:
        mfa_session = _create_mfa_session_token(user_id)
        return {"requires_mfa": True, "mfa_session": mfa_session}
    return TokenResponse(
        access_token=_create_access_token(user_id, is_admin=user.is_admin),
        refresh_token=_create_refresh_token(user_id),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, session: DbSession):
    payload = _decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not a refresh token")
    user_id = payload["sub"]
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return TokenResponse(
        access_token=_create_access_token(user_id, is_admin=user.is_admin),
        refresh_token=_create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserResponse)
async def get_me(request: Request, session: DbSession):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    perms = ADMIN_PERMISSIONS if user.is_admin else (user.permissions or DEFAULT_PERMISSIONS)
    return UserResponse(
        id=str(user.id),
        email=user.email,
        name=user.name,
        timezone=user.timezone,
        is_active=user.is_active,
        is_admin=user.is_admin,
        role=user.role,
        permissions=perms,
        created_at=user.created_at.isoformat(),
        mfa_enabled=user.mfa_enabled,
    )


@router.post("/mfa/verify", response_model=TokenResponse)
async def mfa_verify(req: MFAVerifyRequest, session: DbSession):
    payload = _decode_token(req.mfa_session)
    if payload.get("type") != "mfa_pending":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid MFA session")
    user_id = payload["sub"]
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(req.totp_code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid code")
    return TokenResponse(
        access_token=_create_access_token(user_id, is_admin=user.is_admin),
        refresh_token=_create_refresh_token(user_id),
    )


@router.post("/mfa/setup")
async def mfa_setup(request: Request, session: DbSession):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA already enabled")
    secret = pyotp.random_base32()
    user.mfa_secret = secret
    await session.commit()
    totp = pyotp.TOTP(secret)
    uri = totp.provisioning_uri(name=user.email, issuer_name="Phoenix v2")
    return {"secret": secret, "provisioning_uri": uri}


@router.post("/mfa/confirm")
async def mfa_confirm(request: Request, req: MFAConfirmRequest, session: DbSession):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.mfa_enabled:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="MFA already enabled")
    if not user.mfa_secret:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Call /mfa/setup first")
    totp = pyotp.TOTP(user.mfa_secret)
    if not totp.verify(req.totp_code, valid_window=1):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid code")
    user.mfa_enabled = True
    await session.commit()
    return {"status": "mfa_enabled", "message": "Two-factor authentication has been enabled."}


@router.post("/mfa/disable")
async def mfa_disable(request: Request, session: DbSession):
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
    return {"status": "mfa_disabled", "message": "MFA has been disabled."}

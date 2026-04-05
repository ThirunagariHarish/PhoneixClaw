"""
Admin API routes: users CRUD, roles, API keys, audit log.

M3.7: Admin & User Management Tab.
"""

import secrets
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import DbSession
from shared.crypto.credentials import decrypt_value, encrypt_value
from shared.db.models.api_key import ApiKeyEntry
from shared.db.models.audit_log import AuditLog
from shared.db.models.user import User

router = APIRouter(prefix="/api/v2/admin", tags=["admin"])


def _mask_api_key(plaintext: str) -> str:
    if len(plaintext) <= 8:
        return "••••••••"
    return f"{plaintext[:4]}…{plaintext[-4:]}"


async def _require_admin(request: Request, session: AsyncSession) -> None:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if getattr(request.state, "is_admin", False):
        return
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user and (user.is_admin or (user.role or "").lower() == "admin"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


class UserCreate(BaseModel):
    email: str = Field(..., min_length=1)
    password: str = Field(..., min_length=8)
    name: str | None = None
    role: str = "trader"


class UserUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    is_active: bool | None = None


class RoleCreate(BaseModel):
    name: str = Field(..., min_length=1)
    permissions: dict[str, bool] = Field(default_factory=dict)


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1)
    key_type: str = "api"
    provider: str = "phoenix"


class ApiKeyUpdate(BaseModel):
    name: str | None = None
    is_active: bool | None = None


@router.get("/users")
async def list_users(session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    return [{"id": str(u.id), "email": u.email, "name": u.name, "role": u.role, "is_active": u.is_active} for u in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate, session: DbSession, request: Request):
    await _require_admin(request, session)
    import bcrypt
    existing = await session.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")
    user = User(
        id=uuid.uuid4(),
        email=payload.email,
        hashed_password=bcrypt.hashpw(payload.password.encode(), bcrypt.gensalt()).decode(),
        name=payload.name,
        role=payload.role,
    )
    session.add(user)
    await session.commit()
    return {"id": str(user.id), "email": user.email, "role": user.role}


@router.put("/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if payload.name is not None:
        user.name = payload.name
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    await session.commit()
    return {"id": str(user.id), "email": user.email, "role": user.role, "is_active": user.is_active}


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    await session.delete(user)
    await session.commit()


@router.get("/roles")
async def list_roles(session: DbSession, request: Request):
    await _require_admin(request, session)
    return [{"id": "admin", "name": "admin", "permissions": {"*": True}}, {"id": "trader", "name": "trader", "permissions": {"agents:read": True, "trades:read": True}}]


@router.post("/roles", status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate, session: DbSession, request: Request):
    await _require_admin(request, session)
    return {"id": payload.name.lower(), "name": payload.name, "permissions": payload.permissions}


@router.get("/api-keys")
async def list_api_keys(session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(ApiKeyEntry).order_by(ApiKeyEntry.created_at.desc()))
    keys = result.scalars().all()
    return [{"id": str(k.id), "name": k.name, "key_type": k.key_type, "masked_value": k.masked_value, "is_active": k.is_active} for k in keys]


@router.post("/api-keys", status_code=status.HTTP_201_CREATED)
async def create_api_key(payload: ApiKeyCreate, session: DbSession, request: Request):
    await _require_admin(request, session)
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        uid = uuid.UUID(user_id)
    else:
        first_user = (await session.execute(select(User).limit(1))).scalar_one_or_none()
        if not first_user:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No users exist; create a user first")
        uid = first_user.id
    plaintext = f"sk_{secrets.token_urlsafe(32)}"
    key = ApiKeyEntry(
        id=uuid.uuid4(),
        name=payload.name,
        key_type=payload.key_type,
        provider=payload.provider,
        encrypted_value=encrypt_value(plaintext),
        masked_value=_mask_api_key(plaintext),
        user_id=uid,
    )
    session.add(key)
    await session.commit()
    return {
        "id": str(key.id),
        "name": key.name,
        "masked_value": key.masked_value,
        "secret": plaintext,
    }


@router.put("/api-keys/{key_id}")
async def update_api_key(key_id: str, payload: ApiKeyUpdate, session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(ApiKeyEntry).where(ApiKeyEntry.id == uuid.UUID(key_id)))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    if payload.name is not None:
        key.name = payload.name
    if payload.is_active is not None:
        key.is_active = payload.is_active
    await session.commit()
    return {"id": str(key.id), "name": key.name, "is_active": key.is_active}


@router.delete("/api-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_api_key(key_id: str, session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(ApiKeyEntry).where(ApiKeyEntry.id == uuid.UUID(key_id)))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    await session.delete(key)
    await session.commit()


@router.post("/api-keys/{key_id}/test")
async def test_api_key(key_id: str, session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(ApiKeyEntry).where(ApiKeyEntry.id == uuid.UUID(key_id)))
    key = result.scalar_one_or_none()
    if not key:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
    key.last_tested_at = datetime.now(timezone.utc)
    try:
        decrypt_value(key.encrypted_value)
        key.is_valid = True
    except Exception:
        key.is_valid = False
    await session.commit()
    return {"status": "ok", "is_valid": key.is_valid}


@router.get("/audit-log")
async def list_audit_log(session: DbSession, request: Request, limit: int = 100):
    await _require_admin(request, session)
    result = await session.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    logs = result.scalars().all()
    return [{"id": str(l.id), "user_id": str(l.user_id) if l.user_id else None, "action": l.action, "target_type": l.target_type, "details": l.details, "created_at": l.created_at.isoformat()} for l in logs]

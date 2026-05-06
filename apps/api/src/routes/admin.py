"""
Admin API routes: users CRUD, roles, API keys, audit log.

M3.7: Admin & User Management Tab.
"""
from __future__ import annotations

import json
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
    is_admin: bool | None = None


@router.get("/trade-outcomes")
async def list_trade_outcomes(session: DbSession, request: Request,
                                days: int = 30):
    """Dump recent trade_outcomes_feedback rows grouped by agent.

    Consumed by the trade-feedback-agent to compute bias multipliers without
    touching DB models directly.
    """
    await _require_admin(request, session)
    from sqlalchemy import text

    try:
        res = await session.execute(
            text(
                "SELECT agent_id, predicted_sl_mult, actual_mae_atr, "
                "predicted_tp_mult, actual_mfe_atr, predicted_slip_bps, "
                "actual_slip_bps, closed_at FROM trade_outcomes_feedback "
                "WHERE closed_at >= NOW() - (:days || ' days')::interval"
            ),
            {"days": days},
        )
        rows = res.all()
    except Exception as exc:
        return {"per_agent": {}, "error": str(exc)[:200]}

    per_agent: dict[str, list[dict]] = {}
    for r in rows:
        aid = str(r[0])
        per_agent.setdefault(aid, []).append({
            "predicted_sl_mult": float(r[1]) if r[1] is not None else None,
            "actual_mae_atr": float(r[2]) if r[2] is not None else None,
            "predicted_tp_mult": float(r[3]) if r[3] is not None else None,
            "actual_mfe_atr": float(r[4]) if r[4] is not None else None,
            "predicted_slip_bps": float(r[5]) if r[5] is not None else None,
            "actual_slip_bps": float(r[6]) if r[6] is not None else None,
            "closed_at": r[7].isoformat() if r[7] else None,
        })

    return {
        "days": days,
        "row_count": len(rows),
        "per_agent": per_agent,
    }


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
    if payload.is_admin is not None:
        user.is_admin = payload.is_admin
    await session.commit()
    return {
        "id": str(user.id),
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "is_admin": user.is_admin,
    }


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


# Phase B.9: DLQ operator endpoints

@router.get("/dlq")
async def list_dlq(
    session: DbSession,
    request: Request,
    connector_id: str | None = None,
    page: int = 1,
    limit: int = 50,
):
    """List unresolved dead letter messages with pagination."""
    await _require_admin(request, session)
    from sqlalchemy import text

    offset = (page - 1) * limit
    query = text("""
        SELECT id, connector_id, payload, error, attempts, created_at
        FROM dead_letter_messages
        WHERE resolved = false
    """ + (" AND connector_id = :connector_id" if connector_id else "") + """
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """)
    params = {"limit": limit, "offset": offset}
    if connector_id:
        params["connector_id"] = connector_id

    result = await session.execute(query, params)
    rows = result.all()

    return {
        "items": [
            {
                "id": str(r[0]),
                "connector_id": r[1],
                "payload": r[2],
                "error": r[3],
                "attempts": r[4],
                "created_at": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ],
        "page": page,
        "limit": limit,
    }


@router.post("/dlq/{dlq_id}/replay", status_code=status.HTTP_202_ACCEPTED)
async def replay_dlq_message(dlq_id: str, session: DbSession, request: Request):
    """Re-inject a DLQ message into Redis stream; increment attempts."""
    await _require_admin(request, session)
    from sqlalchemy import text

    result = await session.execute(
        text(
            "SELECT connector_id, payload, attempts FROM dead_letter_messages WHERE id = :id AND resolved = false"
        ),
        {"id": dlq_id},
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="DLQ message not found or already resolved"
        )

    connector_id, payload_json, attempts = row
    payload = json.loads(payload_json)

    # Re-inject into Redis stream
    try:
        import os

        import redis.asyncio as aioredis

        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        stream_key = f"stream:channel:{connector_id}"
        stream_payload = {k: str(v) for k, v in payload.items()}
        await redis_client.xadd(stream_key, stream_payload)
        await redis_client.aclose()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Redis re-injection failed: {exc}"
        )

    # Increment attempts
    await session.execute(
        text("UPDATE dead_letter_messages SET attempts = :attempts WHERE id = :id"),
        {"attempts": attempts + 1, "id": dlq_id},
    )
    await session.commit()

    return {"status": "replayed", "id": dlq_id, "attempts": attempts + 1}


@router.post("/dlq/{dlq_id}/discard", status_code=status.HTTP_200_OK)
async def discard_dlq_message(dlq_id: str, session: DbSession, request: Request):
    """Mark a DLQ message as resolved."""
    await _require_admin(request, session)
    from sqlalchemy import text

    result = await session.execute(
        text("SELECT id FROM dead_letter_messages WHERE id = :id AND resolved = false"),
        {"id": dlq_id},
    )
    if not result.one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="DLQ message not found or already resolved")

    await session.execute(
        text("UPDATE dead_letter_messages SET resolved = true, resolved_at = NOW() WHERE id = :id"),
        {"id": dlq_id},
    )
    await session.commit()

    return {"status": "discarded", "id": dlq_id}


@router.get("/agent-health")
async def list_agent_health(session: DbSession, request: Request):
    """Return all agent_sessions with heartbeat age and stale flag (>5min = stale)."""
    await _require_admin(request, session)
    from shared.db.models.agent_session import AgentSession

    result = await session.execute(select(AgentSession).order_by(AgentSession.started_at.desc()))
    sessions = result.scalars().all()

    output = []
    for s in sessions:
        heartbeat_age_sec = None
        is_stale = False
        if s.last_heartbeat:
            delta = datetime.now(timezone.utc) - s.last_heartbeat
            heartbeat_age_sec = int(delta.total_seconds())
            is_stale = heartbeat_age_sec > 300

        output.append({
            "id": str(s.id),
            "agent_id": str(s.agent_id),
            "session_id": s.session_id,
            "agent_type": s.agent_type,
            "status": s.status,
            "session_role": s.session_role,
            "last_heartbeat": s.last_heartbeat.isoformat() if s.last_heartbeat else None,
            "heartbeat_age_sec": heartbeat_age_sec,
            "is_stale": is_stale,
            "started_at": s.started_at.isoformat() if s.started_at else None,
        })

    return output

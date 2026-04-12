"""
Admin-only invitation CRUD for invitation-only account creation.
"""

import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.src.deps import DbSession
from shared.db.models.invitation import Invitation
from shared.db.models.user import User

router = APIRouter(prefix="/api/v2/admin/invitations", tags=["invitations"])


async def _require_admin(request: Request, session: AsyncSession) -> None:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    if getattr(request.state, "is_admin", False):
        return
    try:
        uid = uuid.UUID(str(user_id))
    except (ValueError, TypeError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required") from None
    result = await session.execute(select(User).where(User.id == uid))
    user = result.scalar_one_or_none()
    if user and (user.is_admin or (user.role or "").lower() == "admin"):
        return
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")


class CreateInvitationRequest(BaseModel):
    expires_at: Optional[str] = None


@router.get("/")
async def list_invitations(session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(Invitation).order_by(Invitation.created_at.desc()))
    invitations = result.scalars().all()

    # Collect user IDs for name lookup
    user_ids = set()
    for inv in invitations:
        if inv.created_by:
            user_ids.add(inv.created_by)
        if inv.used_by:
            user_ids.add(inv.used_by)

    user_names: dict[uuid.UUID, str] = {}
    if user_ids:
        users_result = await session.execute(select(User).where(User.id.in_(user_ids)))
        for u in users_result.scalars().all():
            user_names[u.id] = u.name or u.email

    now = datetime.now(timezone.utc)
    items = []
    for inv in invitations:
        if inv.used_by:
            inv_status = "used"
        elif inv.expires_at and inv.expires_at < now:
            inv_status = "expired"
        else:
            inv_status = "available"

        items.append({
            "id": str(inv.id),
            "code": inv.code,
            "created_by": user_names.get(inv.created_by, None) if inv.created_by else None,
            "used_by": user_names.get(inv.used_by, None) if inv.used_by else None,
            "status": inv_status,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
            "expires_at": inv.expires_at.isoformat() if inv.expires_at else None,
            "used_at": inv.used_at.isoformat() if inv.used_at else None,
        })

    return items


@router.post("/", status_code=status.HTTP_201_CREATED)
async def create_invitation(
    request: Request,
    session: DbSession,
    body: CreateInvitationRequest | None = None,
):
    await _require_admin(request, session)
    user_id = getattr(request.state, "user_id", None)

    expires_at = None
    if body and body.expires_at:
        try:
            expires_at = datetime.fromisoformat(body.expires_at)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid expires_at format. Use ISO 8601.",
            ) from None

    code = secrets.token_urlsafe(16)
    invitation = Invitation(
        id=uuid.uuid4(),
        code=code,
        created_by=uuid.UUID(user_id) if user_id else None,
        expires_at=expires_at,
    )
    session.add(invitation)
    await session.commit()

    return {
        "id": str(invitation.id),
        "code": code,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invitation(invitation_id: str, session: DbSession, request: Request):
    await _require_admin(request, session)
    result = await session.execute(select(Invitation).where(Invitation.id == uuid.UUID(invitation_id)))
    invitation = result.scalar_one_or_none()
    if not invitation:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if invitation.used_by:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete an already-used invitation",
        )
    await session.delete(invitation)
    await session.commit()

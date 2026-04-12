"""
User profile routes: get and update profile, preferences.
"""

import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select

from apps.api.src.deps import DbSession
from shared.db.models.user import User

router = APIRouter(prefix="/api/v2/user", tags=["user"])


class ProfileResponse(BaseModel):
    name: Optional[str] = None
    email: str
    timezone: str


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    timezone: Optional[str] = None


def _get_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    return user_id


@router.get("/profile")
async def get_profile(request: Request, session: DbSession):
    user_id = _get_user_id(request)
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "name": user.name or "",
        "email": user.email,
        "timezone": user.timezone or "UTC",
    }


@router.put("/profile")
async def update_profile(request: Request, body: ProfileUpdateRequest, session: DbSession):
    user_id = _get_user_id(request)
    result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if body.name is not None:
        user.name = body.name
    if body.email is not None:
        user.email = body.email
    if body.timezone is not None:
        user.timezone = body.timezone

    await session.commit()
    return {
        "name": user.name or "",
        "email": user.email,
        "timezone": user.timezone or "UTC",
    }

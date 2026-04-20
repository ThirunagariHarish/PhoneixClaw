"""
User repository with email lookup and deactivation.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, desc

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.user import User


class UserRepository(BaseRepository):

    def __init__(self, session):
        super().__init__(session, User)

    async def get_by_email(self, email: str) -> User | None:
        result = await self.session.execute(
            select(User).where(User.email == email)
        )
        return result.scalar_one_or_none()

    async def list_users(
        self,
        limit: int = 50,
        offset: int = 0,
    ) -> list[User]:
        stmt = (
            select(User)
            .order_by(desc(User.created_at))
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def deactivate(self, id: UUID) -> User | None:
        row = await self.get_by_id(id)
        if not row:
            return None
        row.is_active = False
        await self.session.flush()
        await self.session.refresh(row)
        return row

"""
Automation repository with user, active-state filters and run recording.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import desc, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.task import Automation


class AutomationRepository(BaseRepository):

    def __init__(self, session):
        super().__init__(session, Automation)

    async def list_automations(
        self,
        user_id: UUID | None = None,
        is_active: bool | None = None,
        limit: int = 50,
    ) -> list[Automation]:
        stmt = select(Automation).order_by(desc(Automation.created_at))
        if user_id is not None:
            stmt = stmt.where(Automation.user_id == user_id)
        if is_active is not None:
            stmt = stmt.where(Automation.is_active == is_active)
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, id: UUID) -> bool:
        return await self.delete_by_id(id)

    async def record_run(self, id: UUID) -> Automation | None:
        row = await self.get_by_id(id)
        if not row:
            return None
        row.run_count = (row.run_count or 0) + 1
        row.last_run_at = datetime.now(timezone.utc)
        await self.session.flush()
        await self.session.refresh(row)
        return row

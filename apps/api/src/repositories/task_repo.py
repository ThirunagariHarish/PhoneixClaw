"""
Task repository with status, creator, and move operations.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, desc

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.task import Task


class TaskRepository(BaseRepository):

    def __init__(self, session):
        super().__init__(session, Task)

    async def list_tasks(
        self,
        status: str | None = None,
        created_by: UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Task]:
        stmt = select(Task).order_by(desc(Task.created_at))
        if status is not None:
            stmt = stmt.where(Task.status == status)
        if created_by is not None:
            stmt = stmt.where(Task.created_by == created_by)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def move(self, id: UUID, new_status: str) -> Task | None:
        row = await self.get_by_id(id)
        if not row:
            return None
        row.status = new_status
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete(self, id: UUID) -> bool:
        return await self.delete_by_id(id)

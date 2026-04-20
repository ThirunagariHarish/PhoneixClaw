"""
Base repository with common CRUD operations for Phoenix v2 API.
"""
from __future__ import annotations

from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


class BaseRepository:
    """Generic async repository with standard CRUD operations."""

    def __init__(self, session: AsyncSession, model: type[T]):
        self.session = session
        self.model = model

    async def get_by_id(self, id: UUID) -> T | None:
        """Fetch a single row by primary key."""
        result = await self.session.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def list_all(self, skip: int = 0, limit: int = 50) -> list[T]:
        """List rows with pagination."""
        stmt = select(self.model).offset(skip).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> T:
        """Create a new row from a dict of attributes."""
        row = self.model(**data)
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update(self, id: UUID, data: dict[str, Any]) -> T | None:
        """Update an existing row by id. Returns None if not found."""
        row = await self.get_by_id(id)
        if not row:
            return None
        for key, value in data.items():
            if hasattr(row, key):
                setattr(row, key, value)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_by_id(self, id: UUID) -> bool:
        """Delete a row by id. Returns True if deleted, False if not found."""
        result = await self.session.execute(delete(self.model).where(self.model.id == id))
        return result.rowcount > 0

    async def count(self) -> int:
        """Return total row count."""
        result = await self.session.execute(select(func.count(self.model.id)))
        return result.scalar() or 0

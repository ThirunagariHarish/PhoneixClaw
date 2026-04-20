"""
Skill repository with category and active-state filters.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, desc

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.skill import Skill


class SkillRepository(BaseRepository):

    def __init__(self, session):
        super().__init__(session, Skill)

    async def list_skills(
        self,
        category: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Skill]:
        stmt = select(Skill).order_by(desc(Skill.created_at))
        if category is not None:
            stmt = stmt.where(Skill.category == category)
        if is_active is not None:
            stmt = stmt.where(Skill.is_active == is_active)
        stmt = stmt.offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, name: str) -> Skill | None:
        result = await self.session.execute(
            select(Skill).where(Skill.name == name)
        )
        return result.scalar_one_or_none()

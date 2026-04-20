"""
AgentBacktest repository with agent and status filters.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select, desc

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.agent import AgentBacktest


class BacktestRepository(BaseRepository):

    def __init__(self, session):
        super().__init__(session, AgentBacktest)

    async def list_by_agent(
        self,
        agent_id: UUID,
        status: str | None = None,
        limit: int = 20,
    ) -> list[AgentBacktest]:
        stmt = (
            select(AgentBacktest)
            .where(AgentBacktest.agent_id == agent_id)
            .order_by(desc(AgentBacktest.created_at))
        )
        if status is not None:
            stmt = stmt.where(AgentBacktest.status == status)
        stmt = stmt.limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def update_status(
        self,
        id: UUID,
        status: str,
        metrics: dict[str, Any] | None = None,
    ) -> AgentBacktest | None:
        row = await self.get_by_id(id)
        if not row:
            return None
        row.status = status
        if metrics is not None:
            row.metrics = metrics
        await self.session.flush()
        await self.session.refresh(row)
        return row

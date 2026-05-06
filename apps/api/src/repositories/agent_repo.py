"""
Agent repository with instance, type, and status filters.
"""

from uuid import UUID

from sqlalchemy import desc, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.agent import Agent


class AgentRepository(BaseRepository):
    """Repository for Agent with instance, type, and status filters."""

    def __init__(self, session):
        super().__init__(session, Agent)

    async def list_by_instance(self, instance_id: UUID, skip: int = 0, limit: int = 50) -> list[Agent]:
        """List agents for a given OpenClaw instance."""
        stmt = (
            select(Agent)
            .where(Agent.instance_id == instance_id)
            .order_by(desc(Agent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_type(self, agent_type: str, skip: int = 0, limit: int = 50) -> list[Agent]:
        """List agents filtered by type (trading, strategy, monitoring, task, dev)."""
        stmt = (
            select(Agent)
            .where(Agent.type == agent_type)
            .order_by(desc(Agent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_status(self, status: str, skip: int = 0, limit: int = 50) -> list[Agent]:
        """List agents filtered by status (CREATED, RUNNING, PAUSED, BACKTESTING)."""
        stmt = (
            select(Agent)
            .where(Agent.status == status)
            .order_by(desc(Agent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

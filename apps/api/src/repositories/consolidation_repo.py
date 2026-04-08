"""
Consolidation repository — CRUD for ConsolidationRun records.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc, select, text

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.consolidation import ConsolidationRun


class ConsolidationRepository(BaseRepository):
    """Repository for ConsolidationRun with query helpers."""

    def __init__(self, session: Any) -> None:
        super().__init__(session, ConsolidationRun)

    async def create_run(
        self,
        agent_id: UUID,
        run_type: str = "nightly",
        scheduled_for: datetime | None = None,
    ) -> ConsolidationRun:
        """Create a new pending consolidation run record."""
        run = ConsolidationRun(
            id=uuid.uuid4(),
            agent_id=agent_id,
            run_type=run_type,
            status="pending",
            scheduled_for=scheduled_for,
        )
        self.session.add(run)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def update_status(self, run_id: UUID, status: str, **kwargs: Any) -> ConsolidationRun | None:
        """Update the status (and any extra columns) of a run record."""
        run = await self.get_by_id(run_id)
        if not run:
            return None
        run.status = status
        for key, value in kwargs.items():
            if hasattr(run, key):
                setattr(run, key, value)
        await self.session.flush()
        await self.session.refresh(run)
        return run

    async def get_latest_for_agent(self, agent_id: UUID) -> ConsolidationRun | None:
        """Return the most recently created run for an agent."""
        stmt = (
            select(ConsolidationRun)
            .where(ConsolidationRun.agent_id == agent_id)
            .order_by(desc(ConsolidationRun.created_at))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_for_agent(self, agent_id: UUID, limit: int = 10) -> list[ConsolidationRun]:
        """Return the most recent runs for an agent, newest first."""
        stmt = (
            select(ConsolidationRun)
            .where(ConsolidationRun.agent_id == agent_id)
            .order_by(desc(ConsolidationRun.created_at))
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_agents_due_for_consolidation(self) -> list[UUID]:
        """Return agent_ids where manifest->>'consolidation_enabled' = 'true'."""
        stmt = text(
            "SELECT id FROM agents WHERE manifest->>'consolidation_enabled' = 'true'"
        )
        result = await self.session.execute(stmt)
        return [row[0] for row in result.fetchall()]

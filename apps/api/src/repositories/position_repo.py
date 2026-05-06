"""
Position repository with open/closed and summary queries.
"""

from uuid import UUID

from sqlalchemy import desc, func, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.trade import Position


class PositionRepository(BaseRepository):
    """Repository for Position with open/closed and summary queries."""

    def __init__(self, session):
        super().__init__(session, Position)

    async def list_open(self, skip: int = 0, limit: int = 50) -> list[Position]:
        """List open positions ordered by opened_at."""
        stmt = (
            select(Position)
            .where(Position.status == "OPEN")
            .order_by(desc(Position.opened_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_closed(self, skip: int = 0, limit: int = 50) -> list[Position]:
        """List closed positions ordered by closed_at."""
        stmt = (
            select(Position)
            .where(Position.status == "CLOSED")
            .order_by(desc(Position.closed_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_summary(self) -> dict:
        """Aggregate position summary (open count, unrealized/realized PnL)."""
        open_count = await self.session.execute(
            select(func.count(Position.id)).where(Position.status == "OPEN")
        )
        total_unrealized = await self.session.execute(
            select(func.coalesce(func.sum(Position.unrealized_pnl), 0)).where(Position.status == "OPEN")
        )
        total_realized = await self.session.execute(
            select(func.coalesce(func.sum(Position.realized_pnl), 0)).where(Position.status == "CLOSED")
        )
        return {
            "open_positions": open_count.scalar() or 0,
            "total_unrealized_pnl": float(total_unrealized.scalar() or 0),
            "total_realized_pnl": float(total_realized.scalar() or 0),
        }

    async def list_by_agent(self, agent_id: UUID, skip: int = 0, limit: int = 50) -> list[Position]:
        """List positions for a given agent."""
        stmt = (
            select(Position)
            .where(Position.agent_id == agent_id)
            .order_by(desc(Position.opened_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

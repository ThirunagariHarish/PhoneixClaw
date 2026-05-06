"""
Trade intent repository with domain-specific queries.
"""

from uuid import UUID

from sqlalchemy import desc, func, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.trade import TradeIntent


class TradeIntentRepository(BaseRepository):
    """Repository for TradeIntent with status, agent, and symbol filters."""

    def __init__(self, session):
        super().__init__(session, TradeIntent)

    async def list_by_status(self, status: str, skip: int = 0, limit: int = 50) -> list[TradeIntent]:
        """List trade intents filtered by status."""
        stmt = (
            select(TradeIntent)
            .where(TradeIntent.status == status)
            .order_by(desc(TradeIntent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_agent(self, agent_id: UUID, skip: int = 0, limit: int = 50) -> list[TradeIntent]:
        """List trade intents for a given agent."""
        stmt = (
            select(TradeIntent)
            .where(TradeIntent.agent_id == agent_id)
            .order_by(desc(TradeIntent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_symbol(self, symbol: str, skip: int = 0, limit: int = 50) -> list[TradeIntent]:
        """List trade intents for a given symbol."""
        stmt = (
            select(TradeIntent)
            .where(TradeIntent.symbol == symbol.upper())
            .order_by(desc(TradeIntent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_recent(self, skip: int = 0, limit: int = 50) -> list[TradeIntent]:
        """List trade intents ordered by created_at desc."""
        stmt = (
            select(TradeIntent)
            .order_by(desc(TradeIntent.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_stats(self) -> dict:
        """Aggregate trade statistics by status."""
        total = await self.session.execute(select(func.count(TradeIntent.id)))
        filled = await self.session.execute(
            select(func.count(TradeIntent.id)).where(TradeIntent.status == "FILLED")
        )
        rejected = await self.session.execute(
            select(func.count(TradeIntent.id)).where(TradeIntent.status == "REJECTED")
        )
        pending = await self.session.execute(
            select(func.count(TradeIntent.id)).where(TradeIntent.status == "PENDING")
        )
        return {
            "total": total.scalar() or 0,
            "filled": filled.scalar() or 0,
            "rejected": rejected.scalar() or 0,
            "pending": pending.scalar() or 0,
        }

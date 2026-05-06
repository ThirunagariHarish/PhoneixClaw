"""
Connector repository with type and active filters.
"""

from sqlalchemy import desc, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.connector import Connector


class ConnectorRepository(BaseRepository):
    """Repository for Connector with type and active filters."""

    def __init__(self, session):
        super().__init__(session, Connector)

    async def list_by_type(self, connector_type: str, skip: int = 0, limit: int = 50) -> list[Connector]:
        """List connectors filtered by type (discord, reddit, twitter, etc.)."""
        stmt = (
            select(Connector)
            .where(Connector.type == connector_type)
            .order_by(desc(Connector.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_active(self, skip: int = 0, limit: int = 50) -> list[Connector]:
        """List active connectors only."""
        stmt = (
            select(Connector)
            .where(Connector.is_active == True)
            .order_by(desc(Connector.created_at))
            .offset(skip)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

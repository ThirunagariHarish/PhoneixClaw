"""
Wiki repository — CRUD + search for AgentWikiEntry / AgentWikiEntryVersion.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import desc, func, or_, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.wiki import AgentWikiEntry, AgentWikiEntryVersion


class WikiRepository(BaseRepository):
    """Repository for AgentWikiEntry with filtering, versioning, and search."""

    def __init__(self, session):
        super().__init__(session, AgentWikiEntry)

    # ------------------------------------------------------------------
    # List / get
    # ------------------------------------------------------------------

    async def list_for_agent(
        self,
        agent_id: UUID,
        user_id: UUID,  # noqa: ARG002 — reserved for future per-user private entries
        category: str | None = None,
        tag: str | None = None,
        symbol: str | None = None,
        search: str | None = None,
        is_shared: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[AgentWikiEntry], int]:
        """Return (entries, total_count).  IDOR: always scoped to *agent_id*."""
        base = select(AgentWikiEntry).where(
            AgentWikiEntry.agent_id == agent_id,
            AgentWikiEntry.is_active.is_(True),
        )

        if category:
            base = base.where(AgentWikiEntry.category == category)
        if is_shared is not None:
            base = base.where(AgentWikiEntry.is_shared.is_(is_shared))
        if tag:
            base = base.where(AgentWikiEntry.tags.any(tag))
        if symbol:
            base = base.where(AgentWikiEntry.symbols.any(symbol))
        if search:
            pattern = f"%{search}%"
            base = base.where(
                or_(
                    AgentWikiEntry.title.ilike(pattern),
                    AgentWikiEntry.content.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total_result = await self.session.execute(count_stmt)
        total: int = total_result.scalar() or 0

        rows_stmt = (
            base.order_by(desc(AgentWikiEntry.updated_at)).offset(skip).limit(limit)
        )
        rows_result = await self.session.execute(rows_stmt)
        entries = list(rows_result.scalars().all())
        return entries, total

    async def get_entry(self, entry_id: UUID, agent_id: UUID) -> AgentWikiEntry | None:
        """Get single entry.  IDOR-safe: must belong to *agent_id*."""
        stmt = select(AgentWikiEntry).where(
            AgentWikiEntry.id == entry_id,
            AgentWikiEntry.agent_id == agent_id,
            AgentWikiEntry.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_versions(self, entry_id: UUID) -> list[AgentWikiEntryVersion]:
        """Return all version snapshots for an entry, oldest first."""
        stmt = (
            select(AgentWikiEntryVersion)
            .where(AgentWikiEntryVersion.entry_id == entry_id)
            .order_by(AgentWikiEntryVersion.version)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    async def create_entry(self, data: dict) -> AgentWikiEntry:
        """Create entry and write the initial version snapshot (v1)."""
        entry = AgentWikiEntry(**data)
        entry.version = 1
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)

        # initial version snapshot
        snapshot = AgentWikiEntryVersion(
            entry_id=entry.id,
            version=1,
            content=entry.content,
            updated_by=entry.created_by,
            change_reason="initial version",
        )
        self.session.add(snapshot)
        await self.session.flush()
        return entry

    async def update_entry(
        self, entry: AgentWikiEntry, data: dict, updated_by: str
    ) -> AgentWikiEntry:
        """Apply *data* to *entry*, bump version, store version snapshot."""
        for key, value in data.items():
            if hasattr(entry, key) and value is not None:
                setattr(entry, key, value)

        entry.version = (entry.version or 1) + 1

        await self.session.flush()
        await self.session.refresh(entry)

        snapshot = AgentWikiEntryVersion(
            entry_id=entry.id,
            version=entry.version,
            content=entry.content,
            updated_by=updated_by,
            change_reason=data.get("change_reason"),
        )
        self.session.add(snapshot)
        await self.session.flush()
        return entry

    async def soft_delete(self, entry: AgentWikiEntry) -> AgentWikiEntry:
        """Mark entry inactive (soft-delete)."""
        entry.is_active = False
        await self.session.flush()
        await self.session.refresh(entry)
        return entry

    # ------------------------------------------------------------------
    # Search / query
    # ------------------------------------------------------------------

    async def query_entries(
        self,
        agent_id: UUID,
        query_text: str,
        category: str | None = None,
        top_k: int = 10,
        include_shared: bool = True,
        requesting_user_id: UUID | None = None,  # noqa: ARG002
    ) -> list[AgentWikiEntry]:
        """Text-based search on title + content + tags for this agent.

        If *include_shared* is True, also surfaces is_shared=True entries from
        other agents (Phoenix Brain cross-pollination).
        """
        pattern = f"%{query_text}%"
        own_clause = select(AgentWikiEntry).where(
            AgentWikiEntry.agent_id == agent_id,
            AgentWikiEntry.is_active.is_(True),
            or_(
                AgentWikiEntry.title.ilike(pattern),
                AgentWikiEntry.content.ilike(pattern),
                AgentWikiEntry.tags.any(query_text),
            ),
        )
        if category:
            own_clause = own_clause.where(AgentWikiEntry.category == category)

        own_clause = own_clause.order_by(
            desc(AgentWikiEntry.confidence_score), desc(AgentWikiEntry.updated_at)
        ).limit(top_k)

        result = await self.session.execute(own_clause)
        entries: list[AgentWikiEntry] = list(result.scalars().all())

        if include_shared and len(entries) < top_k:
            remaining = top_k - len(entries)
            shared_clause = (
                select(AgentWikiEntry)
                .where(
                    AgentWikiEntry.agent_id != agent_id,
                    AgentWikiEntry.is_active.is_(True),
                    AgentWikiEntry.is_shared.is_(True),
                    or_(
                        AgentWikiEntry.title.ilike(pattern),
                        AgentWikiEntry.content.ilike(pattern),
                        AgentWikiEntry.tags.any(query_text),
                    ),
                )
                .order_by(
                    desc(AgentWikiEntry.confidence_score),
                    desc(AgentWikiEntry.updated_at),
                )
                .limit(remaining)
            )
            if category:
                shared_clause = shared_clause.where(AgentWikiEntry.category == category)

            shared_result = await self.session.execute(shared_clause)
            entries.extend(list(shared_result.scalars().all()))

        return entries

    async def list_shared_entries(
        self,
        category: str | None = None,
        symbol: str | None = None,
        search: str | None = None,
        min_confidence: float = 0.0,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[AgentWikiEntry], int]:
        """Phoenix Brain — all is_shared=True, is_active=True entries."""
        base = select(AgentWikiEntry).where(
            AgentWikiEntry.is_shared.is_(True),
            AgentWikiEntry.is_active.is_(True),
            AgentWikiEntry.confidence_score >= min_confidence,
        )
        if category:
            base = base.where(AgentWikiEntry.category == category)
        if symbol:
            base = base.where(AgentWikiEntry.symbols.any(symbol))
        if search:
            pattern = f"%{search}%"
            base = base.where(
                or_(
                    AgentWikiEntry.title.ilike(pattern),
                    AgentWikiEntry.content.ilike(pattern),
                )
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total_result = await self.session.execute(count_stmt)
        total: int = total_result.scalar() or 0

        rows_stmt = (
            base.order_by(
                desc(AgentWikiEntry.confidence_score), desc(AgentWikiEntry.updated_at)
            )
            .offset(skip)
            .limit(limit)
        )
        rows_result = await self.session.execute(rows_stmt)
        return list(rows_result.scalars().all()), total

    async def export_entries(self, agent_id: UUID, fmt: str = "json") -> list[AgentWikiEntry]:  # noqa: ARG002
        """Return all active entries for the agent (format handling is in the route layer)."""
        stmt = (
            select(AgentWikiEntry)
            .where(
                AgentWikiEntry.agent_id == agent_id,
                AgentWikiEntry.is_active.is_(True),
            )
            .order_by(AgentWikiEntry.category, desc(AgentWikiEntry.updated_at))
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

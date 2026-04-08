"""
Wiki repository — CRUD + search for AgentWikiEntry / AgentWikiEntryVersion.
Implements the interface specified in Phase 0+1 of Agent Knowledge Wiki.
"""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import desc, func, or_, select

from apps.api.src.repositories.base import BaseRepository
from shared.db.models.wiki import AgentWikiEntry, AgentWikiEntryVersion


class WikiRepository(BaseRepository):
    """Repository for AgentWikiEntry with filtering, versioning, and text search."""

    def __init__(self, session):
        super().__init__(session, AgentWikiEntry)

    # ------------------------------------------------------------------
    # List / get
    # ------------------------------------------------------------------

    async def list_entries(
        self,
        agent_id: UUID,
        category: str | None = None,
        tag: str | None = None,
        symbol: str | None = None,
        search: str | None = None,
        is_shared: bool | None = None,
        active_only: bool = True,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[AgentWikiEntry], int]:
        """Return (entries, total_count) scoped to agent_id."""
        base = select(AgentWikiEntry).where(AgentWikiEntry.agent_id == agent_id)
        if active_only:
            base = base.where(AgentWikiEntry.is_active.is_(True))
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

        skip = (page - 1) * per_page
        rows_stmt = (
            base.order_by(desc(AgentWikiEntry.updated_at)).offset(skip).limit(per_page)
        )
        rows_result = await self.session.execute(rows_stmt)
        entries = list(rows_result.scalars().all())
        return entries, total

    async def get_entry(self, entry_id: UUID, agent_id: UUID) -> AgentWikiEntry | None:
        """Get single entry. IDOR-safe: must belong to agent_id."""
        stmt = select(AgentWikiEntry).where(
            AgentWikiEntry.id == entry_id,
            AgentWikiEntry.agent_id == agent_id,
            AgentWikiEntry.is_active.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_entry_versions(self, entry_id: UUID) -> list[AgentWikiEntryVersion]:
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

    async def create_entry(
        self,
        agent_id: UUID,
        user_id: UUID | None,
        category: str,
        title: str,
        content: str,
        tags: list[str] | None = None,
        symbols: list[str] | None = None,
        confidence_score: float = 0.5,
        created_by: str = "agent",
        is_shared: bool = False,
        subcategory: str | None = None,
        trade_ref_ids: list[str] | None = None,
    ) -> AgentWikiEntry:
        """Create entry and write the initial version snapshot (v1)."""
        entry = AgentWikiEntry(
            agent_id=agent_id,
            user_id=user_id,
            category=category,
            subcategory=subcategory,
            title=title,
            content=content,
            tags=tags or [],
            symbols=symbols or [],
            confidence_score=confidence_score,
            trade_ref_ids=trade_ref_ids or [],
            created_by=created_by,
            is_shared=is_shared,
            version=1,
        )
        self.session.add(entry)
        await self.session.flush()
        await self.session.refresh(entry)

        snapshot = AgentWikiEntryVersion(
            entry_id=entry.id,
            version=1,
            content=entry.content,
            updated_by=created_by,
            change_reason="initial version",
        )
        self.session.add(snapshot)
        await self.session.flush()
        return entry

    async def update_entry(
        self,
        entry_id: UUID,
        content: str | None = None,
        tags: list[str] | None = None,
        is_active: bool | None = None,
        is_shared: bool | None = None,
        change_reason: str | None = None,
        updated_by: str = "user",
    ) -> AgentWikiEntry:
        """Apply changes to entry, bump version, store version snapshot."""
        stmt = select(AgentWikiEntry).where(AgentWikiEntry.id == entry_id)
        result = await self.session.execute(stmt)
        entry = result.scalar_one_or_none()
        if not entry:
            raise ValueError(f"Entry {entry_id} not found")

        if content is not None:
            entry.content = content
        if tags is not None:
            entry.tags = tags
        if is_active is not None:
            entry.is_active = is_active
        if is_shared is not None:
            entry.is_shared = is_shared

        entry.version = (entry.version or 1) + 1
        entry.updated_at = datetime.now(timezone.utc)

        await self.session.flush()
        await self.session.refresh(entry)

        snapshot = AgentWikiEntryVersion(
            entry_id=entry.id,
            version=entry.version,
            content=entry.content,
            updated_by=updated_by,
            change_reason=change_reason,
        )
        self.session.add(snapshot)
        await self.session.flush()
        return entry

    async def soft_delete(self, entry_id: UUID) -> None:
        """Mark entry inactive (soft-delete)."""
        stmt = select(AgentWikiEntry).where(AgentWikiEntry.id == entry_id)
        result = await self.session.execute(stmt)
        entry = result.scalar_one_or_none()
        if entry:
            entry.is_active = False
            await self.session.flush()

    # ------------------------------------------------------------------
    # Search / query
    # ------------------------------------------------------------------

    async def query_relevant(
        self,
        agent_id: UUID,
        query_text: str,
        category: str | None = None,
        top_k: int = 10,
        include_shared: bool = True,
    ) -> list[AgentWikiEntry]:
        """Text-based search on title + content + tags ranked by confidence."""
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

    async def get_shared_entries(
        self,
        category: str | None = None,
        symbol: str | None = None,
        search: str | None = None,
        min_confidence: float = 0.0,
        page: int = 1,
        per_page: int = 20,
    ) -> tuple[list[AgentWikiEntry], int]:
        """Cross-agent shared entries (Phoenix Brain)."""
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

        skip = (page - 1) * per_page
        rows_stmt = (
            base.order_by(
                desc(AgentWikiEntry.confidence_score), desc(AgentWikiEntry.updated_at)
            )
            .offset(skip)
            .limit(per_page)
        )
        rows_result = await self.session.execute(rows_stmt)
        return list(rows_result.scalars().all()), total

    async def export_entries(
        self, agent_id: UUID, active_only: bool = True
    ) -> list[AgentWikiEntry]:
        """Return all entries for the agent (no pagination)."""
        stmt = select(AgentWikiEntry).where(AgentWikiEntry.agent_id == agent_id)
        if active_only:
            stmt = stmt.where(AgentWikiEntry.is_active.is_(True))
        stmt = stmt.order_by(AgentWikiEntry.category, desc(AgentWikiEntry.updated_at))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def migrate_from_manifest(
        self, agent_id: UUID, user_id: UUID | None, knowledge_dict: dict
    ) -> list[AgentWikiEntry]:
        """Convert manifest.knowledge dict to wiki entries.

        top_features -> MARKET_PATTERNS
        analyst_profile -> SYMBOL_PROFILES
        """
        created = []
        for key, value in knowledge_dict.items():
            if not value:
                continue
            if key == "top_features":
                category = "MARKET_PATTERNS"
            elif key == "analyst_profile":
                category = "SYMBOL_PROFILES"
            else:
                category = "STRATEGY_LEARNINGS"

            content = value if isinstance(value, str) else str(value)
            entry = await self.create_entry(
                agent_id=agent_id,
                user_id=user_id,
                category=category,
                title=f"Migrated: {key}",
                content=content,
                created_by="agent",
            )
            created.append(entry)
        return created

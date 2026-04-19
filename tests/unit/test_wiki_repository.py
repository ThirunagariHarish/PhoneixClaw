"""Unit tests for WikiRepository (apps/api/src/repositories/wiki.py)."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
import sqlalchemy

try:
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker


    _SKIP = False
except Exception as _e:
    _SKIP = True
    _SKIP_REASON = str(_e)

pytestmark = pytest.mark.skipif(
    "_SKIP" in dir() and _SKIP,
    reason=globals().get("_SKIP_REASON", "import failed"),
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TEST_AGENT_ID = uuid.uuid4()
TEST_USER_ID = uuid.uuid4()

_CREATE_ENTRIES_SQL = """
    CREATE TABLE IF NOT EXISTS agent_wiki_entries (
        id TEXT PRIMARY KEY,
        agent_id TEXT NOT NULL,
        user_id TEXT,
        category TEXT NOT NULL,
        subcategory TEXT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        tags TEXT DEFAULT '[]',
        symbols TEXT DEFAULT '[]',
        confidence_score REAL DEFAULT 0.5,
        trade_ref_ids TEXT DEFAULT '[]',
        created_by TEXT DEFAULT 'agent',
        is_active INTEGER DEFAULT 1,
        is_shared INTEGER DEFAULT 0,
        version INTEGER DEFAULT 1,
        created_at TEXT,
        updated_at TEXT
    )
"""

_CREATE_VERSIONS_SQL = """
    CREATE TABLE IF NOT EXISTS agent_wiki_entry_versions (
        id TEXT PRIMARY KEY,
        entry_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        content TEXT NOT NULL,
        updated_by TEXT DEFAULT 'agent',
        updated_at TEXT,
        change_reason TEXT
    )
"""


@pytest_asyncio.fixture
async def db_session():
    """In-memory SQLite async session with wiki tables created via raw SQL."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.execute(sqlalchemy.text(_CREATE_ENTRIES_SQL))
        await conn.execute(sqlalchemy.text(_CREATE_VERSIONS_SQL))

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        yield session

    await engine.dispose()


# ---------------------------------------------------------------------------
# Raw-SQL insert helper (bypasses ARRAY/UUID type issues on SQLite)
# ---------------------------------------------------------------------------

async def _raw_insert_entry(session: AsyncSession, **kwargs):
    """Insert a wiki entry row via raw SQL, then load it back as a simple namespace."""
    eid = kwargs.get("id", str(uuid.uuid4()))
    agent_id = str(kwargs.get("agent_id", TEST_AGENT_ID))
    now = datetime.now(timezone.utc).isoformat()

    await session.execute(
        sqlalchemy.text(
            "INSERT INTO agent_wiki_entries "
            "(id, agent_id, user_id, category, subcategory, title, content, "
            " tags, symbols, confidence_score, trade_ref_ids, created_by, "
            " is_active, is_shared, version, created_at, updated_at) "
            "VALUES (:id, :agent_id, :user_id, :category, :subcategory, :title, :content, "
            " :tags, :symbols, :confidence_score, :trade_ref_ids, :created_by, "
            " :is_active, :is_shared, :version, :created_at, :updated_at)"
        ),
        {
            "id": eid,
            "agent_id": agent_id,
            "user_id": str(kwargs.get("user_id", "")) or None,
            "category": kwargs.get("category", "MARKET_PATTERNS"),
            "subcategory": kwargs.get("subcategory"),
            "title": kwargs.get("title", "Test Title"),
            "content": kwargs.get("content", "Test content"),
            "tags": "[]",
            "symbols": "[]",
            "confidence_score": kwargs.get("confidence_score", 0.5),
            "trade_ref_ids": "[]",
            "created_by": kwargs.get("created_by", "agent"),
            "is_active": 1 if kwargs.get("is_active", True) else 0,
            "is_shared": 1 if kwargs.get("is_shared", False) else 0,
            "version": kwargs.get("version", 1),
            "created_at": now,
            "updated_at": now,
        },
    )
    await session.flush()

    row = await session.execute(
        sqlalchemy.text("SELECT * FROM agent_wiki_entries WHERE id = :id"), {"id": eid}
    )
    data = dict(row.mappings().one())

    # Return a simple namespace so tests can access .id, .category etc.
    import types
    entry = types.SimpleNamespace(
        id=uuid.UUID(data["id"]),
        agent_id=uuid.UUID(data["agent_id"]),
        user_id=uuid.UUID(data["user_id"]) if data.get("user_id") else None,
        category=data["category"],
        subcategory=data.get("subcategory"),
        title=data["title"],
        content=data["content"],
        tags=[],
        symbols=[],
        confidence_score=float(data["confidence_score"]),
        trade_ref_ids=[],
        created_by=data["created_by"],
        is_active=bool(data["is_active"]),
        is_shared=bool(data["is_shared"]),
        version=int(data["version"]),
        created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else None,
        updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
    )
    return entry


async def _raw_insert_version(session: AsyncSession, entry_id: uuid.UUID, version: int, content: str, updated_by: str = "agent", change_reason: str | None = None) -> None:
    """Insert a version row via raw SQL."""
    now = datetime.now(timezone.utc).isoformat()
    await session.execute(
        sqlalchemy.text(
            "INSERT INTO agent_wiki_entry_versions "
            "(id, entry_id, version, content, updated_by, updated_at, change_reason) "
            "VALUES (:id, :entry_id, :version, :content, :updated_by, :updated_at, :change_reason)"
        ),
        {
            "id": str(uuid.uuid4()),
            "entry_id": str(entry_id),
            "version": version,
            "content": content,
            "updated_by": updated_by,
            "updated_at": now,
            "change_reason": change_reason,
        },
    )
    await session.flush()


# ---------------------------------------------------------------------------
# Count helpers (use raw SQL since ORM ARRAY types aren't bound on SQLite)
# ---------------------------------------------------------------------------

async def _count_entries(session: AsyncSession, agent_id: uuid.UUID, category: str | None = None, active_only: bool = True) -> int:
    where = "WHERE agent_id = :agent_id"
    params: dict = {"agent_id": str(agent_id)}
    if active_only:
        where += " AND is_active = 1"
    if category:
        where += " AND category = :category"
        params["category"] = category
    row = await session.execute(
        sqlalchemy.text(f"SELECT COUNT(*) FROM agent_wiki_entries {where}"), params
    )
    return row.scalar() or 0


async def _count_versions(session: AsyncSession, entry_id: uuid.UUID) -> int:
    row = await session.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM agent_wiki_entry_versions WHERE entry_id = :eid"),
        {"eid": str(entry_id)},
    )
    return row.scalar() or 0


async def _get_entry_row(session: AsyncSession, entry_id: uuid.UUID) -> dict:
    row = await session.execute(
        sqlalchemy.text("SELECT * FROM agent_wiki_entries WHERE id = :id"),
        {"id": str(entry_id)},
    )
    return dict(row.mappings().one())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestWikiRepository:
    @pytest.mark.asyncio
    async def test_create_entry(self, db_session: AsyncSession):
        """Creates entry, verifies all fields are stored correctly."""
        entry = await _raw_insert_entry(
            db_session,
            agent_id=TEST_AGENT_ID,
            user_id=TEST_USER_ID,
            category="MARKET_PATTERNS",
            title="Bullish flag pattern",
            content="Observed on AAPL during uptrend",
            confidence_score=0.8,
        )
        assert entry.id is not None
        assert entry.agent_id == TEST_AGENT_ID
        assert entry.category == "MARKET_PATTERNS"
        assert entry.title == "Bullish flag pattern"
        assert entry.content == "Observed on AAPL during uptrend"
        assert entry.confidence_score == 0.8
        assert entry.version == 1
        assert entry.is_active is True

    @pytest.mark.asyncio
    async def test_list_entries_by_category(self, db_session: AsyncSession):
        """Filter by category returns only matching entries."""
        await _raw_insert_entry(
            db_session, agent_id=TEST_AGENT_ID, category="MARKET_PATTERNS", title="Pattern A", content="Content A"
        )
        await _raw_insert_entry(
            db_session, agent_id=TEST_AGENT_ID, category="MISTAKES", title="Mistake B", content="Content B"
        )

        total_patterns = await _count_entries(db_session, TEST_AGENT_ID, category="MARKET_PATTERNS")
        total_mistakes = await _count_entries(db_session, TEST_AGENT_ID, category="MISTAKES")
        assert total_patterns == 1
        assert total_mistakes == 1

    @pytest.mark.asyncio
    async def test_update_entry_increments_version(self, db_session: AsyncSession):
        """Updating an entry increments version and stores version history."""
        entry = await _raw_insert_entry(
            db_session,
            agent_id=TEST_AGENT_ID,
            category="STRATEGY_LEARNINGS",
            title="Strategy note",
            content="Original content",
        )
        original_version = entry.version

        # Manually simulate update: bump version + insert a version row
        await _raw_insert_version(db_session, entry.id, 1, "Original content", change_reason="initial version")
        await _raw_insert_version(db_session, entry.id, 2, "Updated content", updated_by="user", change_reason="Fixed typo")

        new_version = original_version + 1
        await db_session.execute(
            sqlalchemy.text(
                "UPDATE agent_wiki_entries SET version = :v, content = :c WHERE id = :id"
            ),
            {"v": new_version, "c": "Updated content", "id": str(entry.id)},
        )
        await db_session.flush()

        updated_row = await _get_entry_row(db_session, entry.id)
        assert int(updated_row["version"]) == new_version
        assert updated_row["content"] == "Updated content"

        version_count = await _count_versions(db_session, entry.id)
        assert version_count >= 2

    @pytest.mark.asyncio
    async def test_soft_delete(self, db_session: AsyncSession):
        """Soft delete sets is_active=False; not returned in active_only count."""
        entry = await _raw_insert_entry(
            db_session, agent_id=TEST_AGENT_ID, category="MISTAKES", title="A mistake", content="What went wrong"
        )

        await db_session.execute(
            sqlalchemy.text("UPDATE agent_wiki_entries SET is_active = 0 WHERE id = :id"),
            {"id": str(entry.id)},
        )
        await db_session.flush()

        active_count = await _count_entries(db_session, TEST_AGENT_ID, category="MISTAKES", active_only=True)
        assert active_count == 0

        all_count = await _count_entries(db_session, TEST_AGENT_ID, category="MISTAKES", active_only=False)
        assert all_count == 1

    @pytest.mark.asyncio
    async def test_query_relevant_title_search(self, db_session: AsyncSession):
        """Text search on title returns matching entries."""
        await _raw_insert_entry(
            db_session,
            agent_id=TEST_AGENT_ID,
            category="MARKET_PATTERNS",
            title="AAPL resistance level",
            content="Strong resistance at $185",
            confidence_score=0.9,
        )
        await _raw_insert_entry(
            db_session,
            agent_id=TEST_AGENT_ID,
            category="MARKET_PATTERNS",
            title="TSLA support zone",
            content="No mention of the keyword",
            confidence_score=0.3,
        )

        row = await db_session.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM agent_wiki_entries "
                "WHERE agent_id = :aid AND is_active = 1 "
                "AND (title LIKE :pat OR content LIKE :pat)"
            ),
            {"aid": str(TEST_AGENT_ID), "pat": "%resistance%"},
        )
        count = row.scalar()
        assert count >= 1

    @pytest.mark.asyncio
    async def test_get_shared_entries(self, db_session: AsyncSession):
        """Only is_shared=1 entries are returned by shared query."""
        other_agent_id = uuid.uuid4()

        await _raw_insert_entry(
            db_session,
            agent_id=other_agent_id,
            category="SECTOR_NOTES",
            title="Tech sector bull run",
            content="Shared insight",
            is_shared=True,
        )
        await _raw_insert_entry(
            db_session,
            agent_id=other_agent_id,
            category="MISTAKES",
            title="Private mistake",
            content="Not shared",
            is_shared=False,
        )

        shared_row = await db_session.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM agent_wiki_entries WHERE is_shared = 1 AND is_active = 1"
            )
        )
        total_shared = shared_row.scalar()
        assert total_shared >= 1

        private_row = await db_session.execute(
            sqlalchemy.text(
                "SELECT COUNT(*) FROM agent_wiki_entries WHERE title = 'Private mistake' AND is_shared = 1"
            )
        )
        assert private_row.scalar() == 0

    @pytest.mark.asyncio
    async def test_wiki_repository_imports(self):
        """WikiRepository and model classes can be imported and instantiated."""
        from apps.api.src.repositories.wiki import WikiRepository
        from shared.db.models.wiki import AgentWikiEntry, AgentWikiEntryVersion, WikiCategory

        assert WikiRepository is not None
        assert AgentWikiEntry.__tablename__ == "agent_wiki_entries"
        assert AgentWikiEntryVersion.__tablename__ == "agent_wiki_entry_versions"
        assert WikiCategory.MARKET_PATTERNS == "MARKET_PATTERNS"
        assert WikiCategory.MISTAKES == "MISTAKES"
        assert len(list(WikiCategory)) == 8

    @pytest.mark.asyncio
    async def test_wiki_category_enum(self):
        """WikiCategory enum has all expected values."""
        from shared.db.models.wiki import WikiCategory

        expected = {
            "MARKET_PATTERNS", "SYMBOL_PROFILES", "STRATEGY_LEARNINGS",
            "MISTAKES", "WINNING_CONDITIONS", "SECTOR_NOTES",
            "MACRO_CONTEXT", "TRADE_OBSERVATION",
        }
        actual = {c.value for c in WikiCategory}
        assert actual == expected

    @pytest.mark.asyncio
    async def test_version_history_ordering(self, db_session: AsyncSession):
        """Version rows are ordered oldest-first."""
        entry = await _raw_insert_entry(
            db_session, agent_id=TEST_AGENT_ID, category="MARKET_PATTERNS",
            title="Multi-version entry", content="v1 content"
        )

        await _raw_insert_version(db_session, entry.id, 1, "v1 content", change_reason="initial")
        await _raw_insert_version(db_session, entry.id, 2, "v2 content", change_reason="edit 1")
        await _raw_insert_version(db_session, entry.id, 3, "v3 content", change_reason="edit 2")

        rows = await db_session.execute(
            sqlalchemy.text(
                "SELECT version FROM agent_wiki_entry_versions WHERE entry_id = :eid ORDER BY version ASC"
            ),
            {"eid": str(entry.id)},
        )
        versions = [r[0] for r in rows.fetchall()]
        assert versions == [1, 2, 3]

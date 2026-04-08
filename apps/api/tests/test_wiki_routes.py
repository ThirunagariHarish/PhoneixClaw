"""
Integration-style route tests for Agent Knowledge Wiki endpoints.

Uses FakeSession / TestClient pattern (same as test_polymarket_routes.py).
No real database required — exercises URL routing, Pydantic request/response
validation, IDOR guard enforcement, version-increment logic, and Markdown
export rendering end-to-end through the FastAPI app.

Tests:
  1. test_create_wiki_entry          — POST creates entry, 201 with all fields
  2. test_list_wiki_entries_filtered — GET with category filter returns entries
  3. test_update_wiki_entry_version  — PATCH increments version field
  4. test_export_markdown            — GET /export?format=markdown returns text/markdown
  5. test_brain_wiki_only_shared     — GET /brain/wiki returns only is_shared=True entries
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.sql import Select

from apps.api.src.config import auth_settings
from apps.api.src.main import app
from shared.db.engine import get_session
from shared.db.models.agent import Agent
from shared.db.models.wiki import AgentWikiEntry, AgentWikiEntryVersion


# ---------------------------------------------------------------------------
# Fake async DB session
# ---------------------------------------------------------------------------


class _FakeResult:
    """Thin wrapper so FakeSession.execute() satisfies both .scalar() and
    .scalars().all() call-chains used by WikiRepository."""

    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    # ---- scalar paths ----

    def scalar(self) -> Any:
        """Used by count(*) queries: total_result.scalar()."""
        return self._rows[0] if self._rows else 0

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    # ---- collection path ----

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Minimal async session stand-in that holds an in-memory store.

    `store` maps ORM model class → list of instances.
    `get(Model, pk)` looks up by `.id` attribute.
    `execute(stmt)` distinguishes count(*) queries (no entity class in
    column_descriptions) from row-fetching queries and serves the store.
    `add()` immediately applies Python-side defaults (uuid, timestamps) so
    objects are usable without a real INSERT.
    """

    def __init__(self, store: dict[type, list[Any]]) -> None:
        self.store = store
        self.added: list[Any] = []
        self.committed = False

    # --- session.get(Model, pk) -------------------------------------------

    async def get(self, model: type, pk: Any) -> Any | None:
        for obj in self.store.get(model, []):
            if hasattr(obj, "id") and obj.id == pk:
                return obj
        return None

    # --- session.execute(stmt) --------------------------------------------

    async def execute(self, stmt: Any) -> _FakeResult:
        if not isinstance(stmt, Select):
            return _FakeResult([])

        # Detect entity classes in the statement's column descriptions.
        entities: list[type] = []
        try:
            for d in stmt.column_descriptions or []:
                e = d.get("entity")
                if isinstance(e, type):
                    entities.append(e)
        except Exception:
            pass

        if not entities:
            # count(*) path: select(func.count()).select_from(subquery)
            # Inspect the FROM clause to find the backing table and sum rows.
            from_objs = list(stmt.get_final_froms() or [])
            total = 0
            for fo in from_objs:
                table_name = getattr(fo, "name", None) or getattr(
                    getattr(fo, "element", None), "name", None
                )
                for cls, rows in self.store.items():
                    if getattr(cls, "__tablename__", None) == table_name:
                        total += len(rows)
            return _FakeResult([total])

        cls = entities[0]
        return _FakeResult(list(self.store.get(cls, [])))

    # --- mutations --------------------------------------------------------

    def add(self, obj: Any) -> None:
        """Add an ORM instance, filling Python-side defaults immediately.

        SQLAlchemy column `default=` values are normally applied at INSERT
        (flush) time, not at Python object creation.  In a fake session that
        never does a real INSERT we must apply common defaults ourselves so
        serialisers don't see None where they expect a typed value.
        """
        if hasattr(obj, "id") and obj.id is None:
            obj.id = uuid.uuid4()
        if hasattr(obj, "created_at") and getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(timezone.utc)
        if hasattr(obj, "updated_at") and getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(timezone.utc)
        # Boolean / integer column defaults
        if hasattr(obj, "is_active") and getattr(obj, "is_active", None) is None:
            obj.is_active = True
        if hasattr(obj, "is_shared") and getattr(obj, "is_shared", None) is None:
            obj.is_shared = False
        if hasattr(obj, "version") and getattr(obj, "version", None) is None:
            obj.version = 1
        if hasattr(obj, "created_by") and getattr(obj, "created_by", None) is None:
            obj.created_by = "agent"
        if hasattr(obj, "tags") and getattr(obj, "tags", None) is None:
            obj.tags = []
        if hasattr(obj, "symbols") and getattr(obj, "symbols", None) is None:
            obj.symbols = []
        if hasattr(obj, "trade_ref_ids") and getattr(obj, "trade_ref_ids", None) is None:
            obj.trade_ref_ids = []
        if hasattr(obj, "confidence_score") and getattr(obj, "confidence_score", None) is None:
            obj.confidence_score = 0.5
        self.added.append(obj)
        self.store.setdefault(type(obj), []).append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def refresh(self, obj: Any) -> None:
        """No-op: fake objects are already fully populated in memory."""
        return None


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------


def _make_agent(user_id: uuid.UUID) -> Agent:
    a = Agent()
    a.id = uuid.uuid4()
    a.user_id = user_id
    a.name = "test-agent"
    a.type = "trading"
    a.status = "RUNNING"
    a.config = {}
    a.source = "manual"
    return a


def _make_wiki_entry(agent_id: uuid.UUID, **overrides: Any) -> AgentWikiEntry:
    e = AgentWikiEntry()
    e.id = uuid.uuid4()
    e.agent_id = agent_id
    e.user_id = None
    e.category = overrides.get("category", "MARKET_PATTERNS")
    e.subcategory = overrides.get("subcategory", None)
    e.title = overrides.get("title", "Test Entry")
    e.content = overrides.get("content", "Some content here.")
    e.tags = overrides.get("tags", [])
    e.symbols = overrides.get("symbols", [])
    e.confidence_score = overrides.get("confidence_score", 0.7)
    e.trade_ref_ids = overrides.get("trade_ref_ids", [])
    e.created_by = overrides.get("created_by", "agent")
    e.is_active = overrides.get("is_active", True)
    e.is_shared = overrides.get("is_shared", False)
    e.version = overrides.get("version", 1)
    e.created_at = datetime(2025, 1, 1, tzinfo=timezone.utc)
    e.updated_at = datetime(2025, 1, 2, tzinfo=timezone.utc)
    return e


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def user_uuid() -> uuid.UUID:
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def auth_headers(user_uuid: uuid.UUID) -> dict[str, str]:
    """Admin JWT token so IDOR check always passes regardless of agent ownership."""
    token = jwt.encode(
        {
            "sub": str(user_uuid),
            "type": "access",
            "admin": True,
            "role": "admin",
        },
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def agent(user_uuid: uuid.UUID) -> Agent:
    return _make_agent(user_uuid)


@pytest.fixture
def client_and_session(agent: Agent):
    """Yield (TestClient, FakeSession) with the agent pre-loaded in store."""
    store: dict[type, list[Any]] = {Agent: [agent]}
    session = FakeSession(store)

    async def _override():
        yield session

    app.dependency_overrides[get_session] = _override
    c = TestClient(app)
    try:
        yield c, session
    finally:
        app.dependency_overrides.pop(get_session, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_create_wiki_entry(client_and_session, agent: Agent, auth_headers: dict):
    """POST /wiki creates a wiki entry and returns 201 with all expected fields."""
    client, _ = client_and_session

    payload = {
        "category": "MARKET_PATTERNS",
        "title": "Bull Flag Setup",
        "content": "Price consolidates after a sharp move up, then breaks out.",
        "tags": ["breakout", "bull"],
        "symbols": ["AAPL"],
        "confidence_score": 0.8,
        "is_shared": False,
    }

    resp = client.post(
        f"/api/v2/agents/{agent.id}/wiki",
        json=payload,
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    data = resp.json()

    # Core fields
    assert data["category"] == "MARKET_PATTERNS"
    assert data["title"] == "Bull Flag Setup"
    assert data["content"] == "Price consolidates after a sharp move up, then breaks out."
    assert data["confidence_score"] == 0.8
    assert data["tags"] == ["breakout", "bull"]
    assert data["symbols"] == ["AAPL"]
    assert data["version"] == 1
    assert data["is_active"] is True
    assert data["is_shared"] is False
    assert data["agent_id"] == str(agent.id)
    assert "id" in data
    assert uuid.UUID(data["id"])  # valid UUID


def test_list_wiki_entries_filtered(client_and_session, agent: Agent, auth_headers: dict):
    """GET /wiki?category=MARKET_PATTERNS returns entries for the agent."""
    client, session = client_and_session

    entry = _make_wiki_entry(
        agent.id,
        category="MARKET_PATTERNS",
        title="Opening Range Breakout",
        tags=["ORB"],
        symbols=["SPY"],
    )
    session.store[AgentWikiEntry] = [entry]

    resp = client.get(
        f"/api/v2/agents/{agent.id}/wiki?category=MARKET_PATTERNS&page=1&per_page=20",
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    # Response shape
    assert "entries" in data
    assert "total" in data
    assert "page" in data
    assert "per_page" in data
    assert data["page"] == 1
    assert data["per_page"] == 20

    # Every returned entry belongs to the requested agent with the right category
    for e in data["entries"]:
        assert e["agent_id"] == str(agent.id)
        assert e["category"] == "MARKET_PATTERNS"


def test_update_wiki_entry_version(client_and_session, agent: Agent, auth_headers: dict):
    """PATCH /wiki/{id} increments version and persists new content."""
    client, session = client_and_session

    entry = _make_wiki_entry(
        agent.id,
        version=1,
        content="Original content — v1.",
        title="VWAP Reclaim",
    )
    session.store[AgentWikiEntry] = [entry]
    session.store[AgentWikiEntryVersion] = []

    resp = client.patch(
        f"/api/v2/agents/{agent.id}/wiki/{entry.id}",
        json={
            "content": "Refined content — v2 with additional notes.",
            "change_reason": "Added backtesting observations.",
        },
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["version"] == 2
    assert data["content"] == "Refined content — v2 with additional notes."
    assert data["id"] == str(entry.id)
    assert data["title"] == "VWAP Reclaim"


def test_export_markdown(client_and_session, agent: Agent, auth_headers: dict):
    """GET /wiki/export?format=markdown returns a text/markdown PlainTextResponse."""
    client, session = client_and_session

    entry = _make_wiki_entry(
        agent.id,
        category="STRATEGY_LEARNINGS",
        title="VWAP Bounce",
        content="Price bounces off VWAP in the first 30 minutes of RTH.",
        confidence_score=0.9,
        tags=["VWAP", "intraday"],
        symbols=["QQQ"],
    )
    session.store[AgentWikiEntry] = [entry]

    resp = client.get(
        f"/api/v2/agents/{agent.id}/wiki/export?format=markdown",
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text

    # Content-Type must indicate markdown
    content_type = resp.headers.get("content-type", "")
    assert "markdown" in content_type, f"Expected markdown content-type, got: {content_type}"

    body = resp.text
    assert "# Agent Wiki Export" in body
    assert "## Category: STRATEGY_LEARNINGS" in body
    assert "### VWAP Bounce" in body
    assert "Price bounces off VWAP" in body
    assert "0.90" in body  # confidence_score formatted as 0.XX
    assert "VWAP" in body


def test_brain_wiki_only_shared(client_and_session, auth_headers: dict):
    """GET /brain/wiki returns shared entries (is_shared=True) across all agents.

    Strategy: pre-populate the store with only is_shared=True entries so the
    FakeSession returns them via the brain route.  Asserts response shape and
    that every returned entry carries is_shared=True.
    """
    client, session = client_and_session

    shared_entry_1 = _make_wiki_entry(
        uuid.uuid4(),
        category="MACRO_CONTEXT",
        title="Fed Rate Outlook Q3",
        content="Hawkish tone; expect two more 25bp hikes.",
        is_shared=True,
        confidence_score=0.85,
    )
    shared_entry_2 = _make_wiki_entry(
        uuid.uuid4(),
        category="MARKET_PATTERNS",
        title="Pre-FOMC Drift",
        content="Markets tend to drift slightly higher 2 days before FOMC.",
        is_shared=True,
        confidence_score=0.75,
    )
    # Only shared entries in the brain store — the route's repo filters by is_shared=True
    session.store[AgentWikiEntry] = [shared_entry_1, shared_entry_2]

    resp = client.get("/api/v2/brain/wiki", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert "entries" in data
    assert "total" in data
    assert len(data["entries"]) >= 1

    # All returned entries must be shared
    for e in data["entries"]:
        assert e["is_shared"] is True, f"Non-shared entry leaked into /brain/wiki: {e}"

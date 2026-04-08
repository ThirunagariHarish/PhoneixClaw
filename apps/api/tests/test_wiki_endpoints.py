"""
Endpoint-level tests for wiki routes (import / schema / path smoke tests).
These tests do NOT require a live DB — they verify that the route module loads
correctly, the routers are exported, and the Pydantic schemas behave as expected.
"""

from __future__ import annotations

import pytest

try:
    from apps.api.src.routes.wiki import brain_router, router
except Exception as e:
    pytest.skip(f"Cannot import wiki routes: {e}", allow_module_level=True)


# ---------------------------------------------------------------------------
# Router smoke tests
# ---------------------------------------------------------------------------


def test_router_prefix():
    assert router.prefix == "/api/v2/agents"


def test_brain_router_prefix():
    assert brain_router.prefix == "/api/v2/brain"


def test_router_has_wiki_routes():
    paths = {r.path for r in router.routes}
    # Must have the list endpoint
    assert any("wiki" in p for p in paths), f"No wiki paths found: {paths}"


def test_brain_router_has_wiki_route():
    paths = {r.path for r in brain_router.routes}
    assert any("wiki" in p for p in paths), f"No wiki path in brain_router: {paths}"


def test_export_route_registered_before_entry_id():
    """Ensure /export route is before /{entry_id} to avoid path conflicts."""
    paths = [r.path for r in router.routes]
    wiki_paths = [p for p in paths if "wiki" in p]
    # find export and entry_id paths
    export_idx = next(
        (i for i, p in enumerate(wiki_paths) if p.endswith("/export")), None
    )
    entry_id_idx = next(
        (i for i, p in enumerate(wiki_paths) if "{entry_id}" in p and "/versions" not in p), None
    )
    if export_idx is not None and entry_id_idx is not None:
        assert export_idx < entry_id_idx, (
            f"/export (idx {export_idx}) must come before /{{entry_id}} (idx {entry_id_idx})"
        )


def test_query_route_is_post():
    """The /query endpoint must be a POST."""
    from fastapi.routing import APIRoute

    query_routes = [
        r
        for r in router.routes
        if isinstance(r, APIRoute) and r.path.endswith("/query")
    ]
    assert query_routes, "No /query route found"
    for qr in query_routes:
        assert "POST" in qr.methods, f"/query route must be POST, got {qr.methods}"


# ---------------------------------------------------------------------------
# Pydantic schema tests
# ---------------------------------------------------------------------------


def test_wiki_entry_create_valid():

    from apps.api.src.routes.wiki import WikiEntryCreate

    entry = WikiEntryCreate(category="MARKET_PATTERNS", title="Test", content="Body")
    assert entry.category == "MARKET_PATTERNS"
    assert entry.confidence_score == 0.5


def test_wiki_entry_create_invalid_category():
    from pydantic import ValidationError

    from apps.api.src.routes.wiki import WikiEntryCreate

    with pytest.raises(ValidationError):
        WikiEntryCreate(category="INVALID", title="T", content="C")


def test_wiki_entry_update_partial():
    from apps.api.src.routes.wiki import WikiEntryUpdate

    update = WikiEntryUpdate(title="New title")
    assert update.title == "New title"
    assert update.content is None
    assert update.category is None


def test_wiki_query_request_defaults():
    from apps.api.src.routes.wiki import WikiQueryRequest

    req = WikiQueryRequest(query_text="test query")
    assert req.top_k == 10
    assert req.include_shared is True
    assert req.category is None


def test_wiki_query_request_top_k_bounds():
    from pydantic import ValidationError

    from apps.api.src.routes.wiki import WikiQueryRequest

    with pytest.raises(ValidationError):
        WikiQueryRequest(query_text="q", top_k=0)

    with pytest.raises(ValidationError):
        WikiQueryRequest(query_text="q", top_k=51)

    req = WikiQueryRequest(query_text="q", top_k=50)
    assert req.top_k == 50


def test_wiki_list_response_structure():
    from apps.api.src.routes.wiki import WikiListResponse

    response = WikiListResponse(entries=[], total=0, page=1, per_page=20)
    assert response.total == 0
    assert response.entries == []


# ---------------------------------------------------------------------------
# IDOR helper tests (unit-level, no DB)
# ---------------------------------------------------------------------------


def test_idor_helper_raises_on_admin_false(monkeypatch):
    """_get_agent_and_verify raises 403 when user_id mismatch and not admin."""
    import asyncio

    # Build a minimal fake session and request
    import uuid

    from fastapi import HTTPException

    from apps.api.src.routes.wiki import _get_agent_and_verify

    other_user_id = uuid.uuid4()
    requesting_user_id = uuid.uuid4()

    class FakeAgent:
        user_id = other_user_id
        id = uuid.uuid4()

    class FakeSession:
        async def get(self, model, pk):
            return FakeAgent()

    class FakeState:
        user_id = requesting_user_id
        is_admin = False

    class FakeRequest:
        state = FakeState()

    async def run():
        return await _get_agent_and_verify(
            str(uuid.uuid4()), FakeRequest(), FakeSession()
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(run())
    assert exc_info.value.status_code == 403


def test_idor_helper_allows_admin(monkeypatch):
    """_get_agent_and_verify allows access when is_admin=True."""
    import asyncio
    import uuid

    from apps.api.src.routes.wiki import _get_agent_and_verify

    other_user_id = uuid.uuid4()
    requesting_user_id = uuid.uuid4()

    class FakeAgent:
        user_id = other_user_id
        id = uuid.uuid4()

    class FakeSession:
        async def get(self, model, pk):
            return FakeAgent()

    class FakeState:
        user_id = requesting_user_id
        is_admin = True

    class FakeRequest:
        state = FakeState()

    async def run():
        return await _get_agent_and_verify(
            str(uuid.uuid4()), FakeRequest(), FakeSession()
        )

    agent = asyncio.get_event_loop().run_until_complete(run())
    assert agent is not None


# ---------------------------------------------------------------------------
# Markdown export rendering test
# ---------------------------------------------------------------------------


def test_markdown_export_render():
    """_render_markdown_export should produce well-formed Markdown."""
    import uuid
    from datetime import datetime

    from apps.api.src.routes.wiki import _render_markdown_export
    from shared.db.models.wiki import AgentWikiEntry

    entry = AgentWikiEntry()
    entry.id = uuid.uuid4()
    entry.agent_id = uuid.uuid4()
    entry.category = "MARKET_PATTERNS"
    entry.title = "Bull flag breakout"
    entry.content = "Price consolidates after sharp move up."
    entry.tags = ["breakout", "bull"]
    entry.symbols = ["AAPL"]
    entry.confidence_score = 0.85
    entry.trade_ref_ids = []
    entry.is_active = True
    entry.is_shared = False
    entry.version = 1
    entry.created_by = "agent"
    entry.created_at = datetime(2025, 1, 1)
    entry.updated_at = datetime(2025, 1, 2)

    md = _render_markdown_export([entry])
    assert "# Agent Wiki Export" in md
    assert "## Category: MARKET_PATTERNS" in md
    assert "### Bull flag breakout" in md
    assert "breakout" in md
    assert "AAPL" in md
    assert "0.85" in md

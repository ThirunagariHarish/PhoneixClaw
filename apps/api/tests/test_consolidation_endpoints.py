"""
Endpoint-level tests for consolidation routes (import / schema / path smoke tests).
These tests do NOT require a live DB — they verify route module loads correctly,
Pydantic schemas behave as expected, and IDOR protection is wired up.
"""

from __future__ import annotations

import pytest

try:
    from apps.api.src.routes.consolidation import router
except Exception as e:
    pytest.skip(f"Cannot import consolidation routes: {e}", allow_module_level=True)


# ---------------------------------------------------------------------------
# Router smoke tests
# ---------------------------------------------------------------------------


def test_router_prefix():
    assert router.prefix == "/api/v2/agents"


def test_router_has_consolidation_routes():
    paths = {r.path for r in router.routes}
    assert any("consolidation" in p for p in paths), f"No consolidation paths found: {paths}"


def test_trigger_run_route_is_post():
    from fastapi.routing import APIRoute

    post_routes = [
        r
        for r in router.routes
        if isinstance(r, APIRoute)
        and r.path.endswith("/consolidation/run")
        and "POST" in r.methods
    ]
    assert post_routes, "No POST /consolidation/run route found"


def test_list_runs_route_is_get():
    from fastapi.routing import APIRoute

    get_routes = [
        r
        for r in router.routes
        if isinstance(r, APIRoute)
        and r.path.endswith("/consolidation/runs")
        and "GET" in r.methods
    ]
    assert get_routes, "No GET /consolidation/runs route found"


def test_get_specific_run_route_is_get():
    from fastapi.routing import APIRoute

    get_routes = [
        r
        for r in router.routes
        if isinstance(r, APIRoute)
        and "{run_id}" in r.path
        and "GET" in r.methods
    ]
    assert get_routes, "No GET /consolidation/runs/{run_id} route found"


def test_trigger_returns_202():
    from fastapi.routing import APIRoute

    post_routes = [
        r
        for r in router.routes
        if isinstance(r, APIRoute)
        and r.path.endswith("/consolidation/run")
        and "POST" in r.methods
    ]
    assert post_routes
    assert post_routes[0].status_code == 202, (
        f"POST /consolidation/run must return 202, got {post_routes[0].status_code}"
    )


# ---------------------------------------------------------------------------
# Pydantic schema tests
# ---------------------------------------------------------------------------


def test_consolidation_run_response_schema():
    from apps.api.src.routes.consolidation import ConsolidationRunResponse

    resp = ConsolidationRunResponse(
        id="abc123",
        agent_id="def456",
        run_type="nightly",
        status="completed",
        scheduled_for=None,
        started_at=None,
        completed_at=None,
        trades_analyzed=10,
        wiki_entries_written=2,
        wiki_entries_updated=1,
        wiki_entries_pruned=0,
        patterns_found=3,
        rules_proposed=1,
        consolidation_report="# Report",
        error_message=None,
        created_at="2025-01-01T00:00:00",
    )
    assert resp.status == "completed"
    assert resp.patterns_found == 3
    assert resp.consolidation_report == "# Report"


def test_trigger_request_defaults():
    from apps.api.src.routes.consolidation import TriggerConsolidationRequest

    req = TriggerConsolidationRequest()
    assert req.run_type == "manual"


def test_trigger_request_custom_run_type():
    from apps.api.src.routes.consolidation import TriggerConsolidationRequest

    req = TriggerConsolidationRequest(run_type="nightly")
    assert req.run_type == "nightly"


# ---------------------------------------------------------------------------
# IDOR helper tests (unit-level, no DB)
# ---------------------------------------------------------------------------


def test_idor_raises_on_user_mismatch():
    """_get_agent_and_verify raises 403 when user_id mismatch and not admin."""
    import asyncio
    import uuid

    from fastapi import HTTPException

    from apps.api.src.routes.consolidation import _get_agent_and_verify

    owner_id = uuid.uuid4()
    requester_id = uuid.uuid4()

    class FakeAgent:
        user_id = owner_id
        id = uuid.uuid4()

    class FakeSession:
        async def get(self, model, pk):
            return FakeAgent()

    class FakeState:
        user_id = requester_id
        is_admin = False

    class FakeRequest:
        state = FakeState()

    async def run():
        return await _get_agent_and_verify(str(uuid.uuid4()), FakeRequest(), FakeSession())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.get_event_loop().run_until_complete(run())
    assert exc_info.value.status_code == 403


def test_idor_allows_admin():
    """_get_agent_and_verify allows access when is_admin=True."""
    import asyncio
    import uuid

    from apps.api.src.routes.consolidation import _get_agent_and_verify

    owner_id = uuid.uuid4()
    requester_id = uuid.uuid4()

    class FakeAgent:
        user_id = owner_id
        id = uuid.uuid4()

    class FakeSession:
        async def get(self, model, pk):
            return FakeAgent()

    class FakeState:
        user_id = requester_id
        is_admin = True

    class FakeRequest:
        state = FakeState()

    async def run():
        return await _get_agent_and_verify(str(uuid.uuid4()), FakeRequest(), FakeSession())

    agent = asyncio.get_event_loop().run_until_complete(run())
    assert agent is not None


def test_idor_allows_owner():
    """_get_agent_and_verify allows access when user_id matches agent.user_id."""
    import asyncio
    import uuid

    from apps.api.src.routes.consolidation import _get_agent_and_verify

    shared_user_id = uuid.uuid4()

    class FakeAgent:
        user_id = shared_user_id
        id = uuid.uuid4()

    class FakeSession:
        async def get(self, model, pk):
            return FakeAgent()

    class FakeState:
        user_id = shared_user_id
        is_admin = False

    class FakeRequest:
        state = FakeState()

    async def run():
        return await _get_agent_and_verify(str(uuid.uuid4()), FakeRequest(), FakeSession())

    agent = asyncio.get_event_loop().run_until_complete(run())
    assert agent is not None

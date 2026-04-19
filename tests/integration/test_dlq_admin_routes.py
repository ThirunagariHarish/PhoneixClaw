"""Integration tests for Phase B.9 DLQ admin routes."""

import json
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from apps.api.src.main import app
from shared.db.engine import get_session


@pytest.fixture
async def admin_token():
    """Mock admin JWT token (bypasses auth middleware in test mode)."""
    return "test-admin-token"


@pytest.fixture
async def seed_dlq_messages():
    """Seed DLQ messages for testing."""
    connector_id = "test-connector-123"
    messages = []

    async for session in get_session():
        for i in range(5):
            msg_id = str(uuid.uuid4())
            await session.execute(
                text("""
                    INSERT INTO dead_letter_messages (id, connector_id, payload, error, attempts, resolved)
                    VALUES (:id, :cid, :payload, :error, :attempts, :resolved)
                """),
                {
                    "id": msg_id,
                    "cid": connector_id,
                    "payload": json.dumps({"ticker": "AAPL", "content": f"Test message {i}"}),
                    "error": f"Test error {i}",
                    "attempts": i,
                    "resolved": i >= 3,  # Last 2 are resolved
                },
            )
            messages.append(msg_id)
        await session.commit()

    yield connector_id, messages

    # Cleanup
    async for session in get_session():
        await session.execute(
            text("DELETE FROM dead_letter_messages WHERE connector_id = :cid"),
            {"cid": connector_id},
        )
        await session.commit()


@pytest.mark.asyncio
async def test_list_dlq_unresolved_only(seed_dlq_messages, admin_token):
    """GET /api/v2/admin/dlq returns only unresolved messages."""
    connector_id, message_ids = seed_dlq_messages

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/api/v2/admin/dlq",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    # Only 3 unresolved messages (indices 0, 1, 2)
    assert len(data["items"]) == 3
    for item in data["items"]:
        assert item["connector_id"] == connector_id


@pytest.mark.asyncio
async def test_list_dlq_filter_by_connector(seed_dlq_messages, admin_token):
    """GET /api/v2/admin/dlq?connector_id filters correctly."""
    connector_id, _ = seed_dlq_messages

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            f"/api/v2/admin/dlq?connector_id={connector_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 3
    assert all(item["connector_id"] == connector_id for item in data["items"])


@pytest.mark.asyncio
async def test_discard_dlq_message(seed_dlq_messages, admin_token):
    """POST /api/v2/admin/dlq/{id}/discard marks message as resolved."""
    connector_id, message_ids = seed_dlq_messages
    unresolved_id = message_ids[0]

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            f"/api/v2/admin/dlq/{unresolved_id}/discard",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "discarded"
    assert data["id"] == unresolved_id

    # Verify DB state
    async for session in get_session():
        result = await session.execute(
            text("SELECT resolved, resolved_at FROM dead_letter_messages WHERE id = :id"),
            {"id": unresolved_id},
        )
        row = result.one()
        assert row[0] is True  # resolved
        assert row[1] is not None  # resolved_at


@pytest.mark.asyncio
async def test_discard_already_resolved_returns_404(seed_dlq_messages, admin_token):
    """Discarding an already-resolved message returns 404."""
    _, message_ids = seed_dlq_messages
    resolved_id = message_ids[3]  # Already resolved

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post(
            f"/api/v2/admin/dlq/{resolved_id}/discard",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_agent_health_endpoint(admin_token):
    """GET /api/v2/admin/agent-health returns sessions with heartbeat age."""
    # Seed an agent session
    agent_id = uuid.uuid4()
    session_id = str(uuid.uuid4())

    async for session in get_session():
        await session.execute(
            text("""
                INSERT INTO agents (id, name, type, status)
                VALUES (:id, :name, :type, :status)
            """),
            {"id": str(agent_id), "name": "test-agent", "type": "trading", "status": "RUNNING"},
        )
        await session.execute(
            text("""
                INSERT INTO agent_sessions (id, agent_id, session_id, agent_type, last_heartbeat)
                VALUES (:id, :agent_id, :session_id, :agent_type, :heartbeat)
            """),
            {
                "id": session_id,
                "agent_id": str(agent_id),
                "session_id": session_id,
                "agent_type": "primary",
                "heartbeat": datetime.now(timezone.utc),
            },
        )
        await session.commit()

    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get(
            "/api/v2/admin/agent-health",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert any(s["agent_id"] == str(agent_id) for s in data)

    # Cleanup
    async for session in get_session():
        await session.execute(text("DELETE FROM agent_sessions WHERE id = :id"), {"id": session_id})
        await session.execute(text("DELETE FROM agents WHERE id = :id"), {"id": str(agent_id)})
        await session.commit()

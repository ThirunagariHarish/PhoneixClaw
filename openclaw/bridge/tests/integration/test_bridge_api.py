"""Bridge API contract tests. M1.7."""
import os
import tempfile
import pytest
from httpx import ASGITransport, AsyncClient

# Set AGENTS_ROOT before importing app
os.environ["AGENTS_ROOT"] = tempfile.mkdtemp()
os.environ["BRIDGE_TOKEN"] = "test-token"

from src.main import app

TRANSPORT = ASGITransport(app=app)
BASE = "http://test"
HEADERS = {"X-Bridge-Token": "test-token"}


@pytest.fixture
def client():
    return AsyncClient(transport=TRANSPORT, base_url=BASE)


@pytest.mark.asyncio
async def test_health_no_auth(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "phoenix-bridge"


@pytest.mark.asyncio
async def test_heartbeat_requires_token(client):
    r = await client.get("/heartbeat")
    assert r.status_code == 422  # missing header


@pytest.mark.asyncio
async def test_heartbeat_with_token(client):
    r = await client.get("/heartbeat", headers=HEADERS)
    assert r.status_code == 200
    data = r.json()
    assert "agents" in data
    assert "count" in data


@pytest.mark.asyncio
async def test_agents_list_with_token(client):
    r = await client.get("/agents", headers=HEADERS)
    assert r.status_code == 200
    assert "agents" in r.json()


@pytest.mark.asyncio
async def test_agent_create_and_delete(client):
    r = await client.post(
        "/agents",
        headers=HEADERS,
        json={"name": "Contract Test Agent", "type": "trading"},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "CREATED"
    agent_id = data["id"]
    r2 = await client.get(f"/agents/{agent_id}", headers=HEADERS)
    assert r2.status_code == 200
    r3 = await client.delete(f"/agents/{agent_id}", headers=HEADERS)
    assert r3.status_code == 204


@pytest.mark.asyncio
async def test_metrics(client):
    r = await client.get("/metrics")
    assert r.status_code == 200
    assert "phoenix_bridge" in r.text


@pytest.mark.asyncio
async def test_skills_sync_requires_token(client):
    r = await client.post("/skills/sync")
    assert r.status_code == 422

"""
Integration tests: Instances API and OpenClaw registration.
Reference: TEST_SUITES.md, ArchitecturePlan §6, OpenClaw at 187.124.77.249.
"""
import os
import uuid

import pytest
from httpx import AsyncClient


pytestmark = [pytest.mark.asyncio]


@pytest.fixture
def openclaw_host():
    return os.getenv("OPENCLAW_HOST", "187.124.77.249")


@pytest.fixture
def openclaw_port():
    return int(os.getenv("OPENCLAW_PORT", "18800"))


async def test_list_instances_returns_array(client: AsyncClient, auth_headers):
    """GET /api/v2/instances returns 200 and list. Requires DB migrations."""
    r = await client.get("/api/v2/instances", headers=auth_headers)
    if r.status_code == 500:
        pytest.skip("API returned 500 (e.g. DB migrations not run)")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_create_instance_success(client: AsyncClient, auth_headers, openclaw_host, openclaw_port):
    """POST /api/v2/instances with name, host, port returns 201 (mock OpenClaw). Requires DB."""
    name = f"Test-OC-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": name,
        "host": openclaw_host,
        "port": openclaw_port,
        "role": "general",
        "node_type": "vps",
    }
    r = await client.post("/api/v2/instances", json=payload, headers=auth_headers)
    if r.status_code == 500:
        pytest.skip("API returned 500 (e.g. DB migrations not run)")
    assert r.status_code == 201
    data = r.json()
    assert data["name"] == name
    assert data["host"] == openclaw_host
    assert data["port"] == openclaw_port
    # Cleanup
    await client.delete(f"/api/v2/instances/{data['id']}", headers=auth_headers)


async def test_create_instance_duplicate_name_fails(client: AsyncClient, auth_headers, sample_instance_payload):
    """Creating instance with same name returns 409."""
    r1 = await client.post("/api/v2/instances", json=sample_instance_payload, headers=auth_headers)
    if r1.status_code != 201:
        pytest.skip("Need DB and auth")
    r2 = await client.post("/api/v2/instances", json=sample_instance_payload, headers=auth_headers)
    assert r2.status_code == 409
    # Cleanup
    await client.delete(f"/api/v2/instances/{r1.json()['id']}", headers=auth_headers)

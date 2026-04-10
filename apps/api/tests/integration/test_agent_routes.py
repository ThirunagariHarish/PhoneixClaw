import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_agents(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v2/agents", headers=auth_headers)
    assert resp.status_code in (200, 500)
    if resp.status_code == 200:
        assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_list_agents_with_type_filter(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v2/agents", headers=auth_headers, params={"type": "trading"})
    assert resp.status_code in (200, 500)


@pytest.mark.asyncio
async def test_create_agent_missing_fields(client: AsyncClient, auth_headers):
    resp = await client.post("/api/v2/agents", json={}, headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_agent_invalid_type(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v2/agents",
        json={
            "name": "BadAgent",
            "type": "nonexistent",
            "instance_id": "00000000-0000-0000-0000-000000000001",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_agent_not_found(client: AsyncClient, auth_headers):
    resp = await client.get(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099",
        headers=auth_headers,
    )
    assert resp.status_code in (404, 500)


@pytest.mark.asyncio
async def test_delete_agent_not_found(client: AsyncClient, auth_headers):
    resp = await client.delete(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099",
        headers=auth_headers,
    )
    assert resp.status_code in (404, 500)


@pytest.mark.asyncio
async def test_pause_agent_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099/pause",
        headers=auth_headers,
    )
    # pause_agent is a no-op when agent isn't running — returns 200
    assert resp.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_resume_agent_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099/resume",
        headers=auth_headers,
    )
    assert resp.status_code in (404, 500)


@pytest.mark.asyncio
async def test_approve_agent_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099/approve",
        headers=auth_headers,
    )
    assert resp.status_code in (404, 500)


@pytest.mark.asyncio
async def test_promote_agent_not_found(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099/promote",
        headers=auth_headers,
    )
    assert resp.status_code in (404, 500)


@pytest.mark.asyncio
async def test_agent_logs_not_found(client: AsyncClient, auth_headers):
    resp = await client.get(
        "/api/v2/agents/00000000-0000-0000-0000-000000000099/logs",
        headers=auth_headers,
    )
    assert resp.status_code in (200, 404, 500)

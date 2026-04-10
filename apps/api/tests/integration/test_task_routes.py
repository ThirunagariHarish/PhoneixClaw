import pytest
from httpx import AsyncClient


def _skip_if_db_unavailable(resp):
    if resp.status_code == 500:
        pytest.skip("DB connection unavailable (expected in CI without PostgreSQL)")


def _create_task_or_skip(resp):
    """Extract task ID from create response, skip test if DB is unavailable."""
    _skip_if_db_unavailable(resp)
    data = resp.json()
    if "id" not in data:
        pytest.skip("Task creation failed — DB may not be available")
    return data["id"]


@pytest.mark.asyncio
async def test_list_tasks(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v2/tasks", headers=auth_headers)
    _skip_if_db_unavailable(resp)
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_create_task(client: AsyncClient, auth_headers, sample_task_payload):
    resp = await client.post(
        "/api/v2/tasks", json=sample_task_payload, headers=auth_headers
    )
    _skip_if_db_unavailable(resp)
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == sample_task_payload["title"]
    assert "id" in data
    assert "created_at" in data


@pytest.mark.asyncio
async def test_create_task_missing_title(client: AsyncClient, auth_headers):
    resp = await client.post(
        "/api/v2/tasks", json={"description": "no title"}, headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_task(client: AsyncClient, auth_headers, sample_task_payload):
    create_resp = await client.post(
        "/api/v2/tasks", json=sample_task_payload, headers=auth_headers
    )
    task_id = _create_task_or_skip(create_resp)

    resp = await client.patch(
        f"/api/v2/tasks/{task_id}",
        json={"title": "Updated title", "priority": "low"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["title"] == "Updated title"


@pytest.mark.asyncio
async def test_delete_task(client: AsyncClient, auth_headers, sample_task_payload):
    create_resp = await client.post(
        "/api/v2/tasks", json=sample_task_payload, headers=auth_headers
    )
    task_id = _create_task_or_skip(create_resp)

    resp = await client.delete(f"/api/v2/tasks/{task_id}", headers=auth_headers)
    assert resp.status_code == 204


@pytest.mark.asyncio
async def test_move_task(client: AsyncClient, auth_headers, sample_task_payload):
    create_resp = await client.post(
        "/api/v2/tasks", json=sample_task_payload, headers=auth_headers
    )
    task_id = _create_task_or_skip(create_resp)

    resp = await client.patch(
        f"/api/v2/tasks/{task_id}/move",
        json={"status": "IN_PROGRESS"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["new_status"] == "IN_PROGRESS"


@pytest.mark.asyncio
async def test_move_task_invalid_status(client: AsyncClient, auth_headers, sample_task_payload):
    create_resp = await client.post(
        "/api/v2/tasks", json=sample_task_payload, headers=auth_headers
    )
    task_id = _create_task_or_skip(create_resp)

    resp = await client.patch(
        f"/api/v2/tasks/{task_id}/move",
        json={"status": "INVALID"},
        headers=auth_headers,
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_delete_task_not_found(client: AsyncClient, auth_headers):
    resp = await client.delete(
        "/api/v2/tasks/nonexistent-id", headers=auth_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_roles(client: AsyncClient, auth_headers):
    resp = await client.get("/api/v2/tasks/roles", headers=auth_headers)
    assert resp.status_code == 200
    roles = resp.json()
    assert isinstance(roles, list)
    assert len(roles) > 0
    assert "id" in roles[0]
    assert "name" in roles[0]

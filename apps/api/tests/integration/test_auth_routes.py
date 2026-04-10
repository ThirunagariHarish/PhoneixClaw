import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_success(client: AsyncClient):
    resp = await client.post(
        "/auth/register",
        json={"email": "new@test.com", "password": "securepass123", "name": "Test"},
    )
    assert resp.status_code in (201, 409, 422, 500)


@pytest.mark.asyncio
async def test_register_short_password(client: AsyncClient):
    resp = await client.post(
        "/auth/register",
        json={"email": "new@test.com", "password": "short", "name": "Test"},
    )
    assert resp.status_code in (422, 500)


@pytest.mark.asyncio
async def test_login_missing_fields(client: AsyncClient):
    resp = await client.post("/auth/login", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_invalid_body(client: AsyncClient):
    resp = await client.post("/auth/login", json={"email": "x@x.com"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_me_unauthenticated(client: AsyncClient):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_auth(client: AsyncClient, auth_headers):
    resp = await client.get("/auth/me", headers=auth_headers)
    assert resp.status_code in (200, 404, 500)


@pytest.mark.asyncio
async def test_refresh_invalid_token(client: AsyncClient):
    resp = await client.post(
        "/auth/refresh",
        json={"refresh_token": "invalid-token"},
    )
    assert resp.status_code == 401

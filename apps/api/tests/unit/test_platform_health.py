"""Unit tests for platform health routes.

Tests the /api/v2/platform/* endpoints using httpx mocking to avoid
calling real microservices.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app


def _make_response(status_code: int = 200, json_data: "dict | None" = None) -> httpx.Response:
    """Build a mock httpx.Response."""
    resp = httpx.Response(
        status_code=status_code,
        json=json_data or {},
        request=httpx.Request("GET", "http://mock"),
    )
    return resp


@pytest.mark.asyncio
async def test_platform_health_all_ok() -> None:
    """GET /api/v2/platform/health returns aggregated status when all services respond 200."""
    ok_resp = _make_response(200, {"version": "1.0.0"})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=ok_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"] == "ok"
    assert "services" in data
    for svc in data["services"].values():
        assert svc["status"] == "ok"


@pytest.mark.asyncio
async def test_platform_health_service_timeout() -> None:
    """Services that timeout are reported as 'timeout'."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"] == "degraded"
    for svc in data["services"].values():
        assert svc["status"] == "timeout"


@pytest.mark.asyncio
async def test_platform_health_service_unreachable() -> None:
    """Services that raise connection errors are reported as 'unreachable'."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["overall"] == "degraded"
    for svc in data["services"].values():
        assert svc["status"] == "unreachable"


@pytest.mark.asyncio
async def test_broker_status_proxy_ok() -> None:
    """GET /api/v2/platform/broker/status proxies to broker gateway."""
    broker_resp = _make_response(200, {"authenticated": True, "paper_mode": True})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=broker_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/broker/status")

    assert resp.status_code == 200
    data = resp.json()
    assert data["authenticated"] is True


@pytest.mark.asyncio
async def test_broker_status_proxy_error() -> None:
    """GET /api/v2/platform/broker/status returns 502 when broker is unreachable."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/broker/status")

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_features_proxy_ok() -> None:
    """GET /api/v2/platform/features/{ticker} proxies to feature pipeline."""
    feature_resp = _make_response(200, {"ticker": "AAPL", "features": {"sma_20": 185.5}})

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=feature_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/features/AAPL")

    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "AAPL"


@pytest.mark.asyncio
async def test_predictions_proxy_error() -> None:
    """GET /api/v2/platform/predictions/{agent_id} returns 502 on connection error."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch("apps.api.src.routes.platform_health.httpx.AsyncClient", return_value=mock_client):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/v2/platform/predictions/some-agent-id")

    assert resp.status_code == 502

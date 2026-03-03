"""
Unit tests for API health endpoint.

M1.1 TDD: Health endpoint must return 200 and service name.
Reference: ImplementationPlan.md Section 5, M1.1 Build Items.
"""

import pytest
from httpx import ASGITransport, AsyncClient

from apps.api.src.main import app


@pytest.mark.asyncio
async def test_health_endpoint_returns_200() -> None:
    """GET /health returns 200 and JSON with status and service."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["service"] == "phoenix-api"

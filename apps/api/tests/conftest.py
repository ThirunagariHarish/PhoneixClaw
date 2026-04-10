"""
Pytest fixtures for Phoenix v2 API tests.

Stubs aggregate /health dependencies so unit tests do not require live Postgres/Redis.
"""

from __future__ import annotations

import os
from collections.abc import Generator
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_api.db")
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379")
os.environ.setdefault("JWT_SECRET_KEY", "change-me-in-production")
os.environ.setdefault("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
if not os.environ.get("CREDENTIAL_ENCRYPTION_KEY"):
    os.environ["CREDENTIAL_ENCRYPTION_KEY"] = "5auLTQ2PfTgU_G8sw3-QGC0C9e26Rs_51rBMrfoeR_A="


@pytest.fixture(autouse=True)
def _stub_aggregate_health() -> Generator[None, None, None]:
    """GET /health returns 200 in tests without real infra."""

    async def _ready() -> dict:
        return {
            "status": "ready",
            "checks": {
                "database": {"healthy": True, "latency_ms": 0.1},
                "redis": {"healthy": True, "latency_ms": 0.1},
                "scheduler": {"healthy": True, "jobs": 0},
                "ingestion": {"healthy": True},
                "disk": {"healthy": True},
            },
        }

    with patch(
        "apps.api.src.services.db_health.aggregate_health",
        new=AsyncMock(side_effect=_ready),
    ):
        yield

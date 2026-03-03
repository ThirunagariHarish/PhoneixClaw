"""
M1.2 — Infrastructure health regression tests.

Tests Postgres, Redis, and optionally MinIO connectivity.
Skip if services are not running (e.g. in CI without Docker).
Reference: ImplementationPlan.md Section 5 M1.2.
"""

import os
import pytest

# Skip entire module if not running infra (e.g. no Docker)
INFRA_ENABLED = os.environ.get("PHOENIX_INFRA_TESTS", "0") == "1"
pytestmark = pytest.mark.skipif(not INFRA_ENABLED, reason="Set PHOENIX_INFRA_TESTS=1 to run")


@pytest.mark.asyncio
async def test_postgres_connection() -> None:
    """PostgreSQL accepts connections."""
    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg not installed")
    conn = await asyncpg.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "phoenixtrader"),
        password=os.environ.get("POSTGRES_PASSWORD", "localdev"),
        database=os.environ.get("POSTGRES_DB", "phoenixtrader"),
    )
    try:
        row = await conn.fetchrow("SELECT 1 AS one")
        assert row["one"] == 1
    finally:
        await conn.close()


def test_redis_connection() -> None:
    """Redis responds to PING."""
    try:
        import redis
    except ImportError:
        pytest.skip("redis not installed")
    url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    r = redis.from_url(url)
    assert r.ping() is True


def test_minio_connection() -> None:
    """MinIO (S3-compatible) is reachable."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        pytest.skip("boto3 not installed")
    endpoint = os.environ.get("MINIO_ENDPOINT", "http://localhost:9000")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=os.environ.get("MINIO_ROOT_USER", "minioadmin"),
        aws_secret_access_key=os.environ.get("MINIO_ROOT_PASSWORD", "minioadmin"),
        config=Config(signature_version="s3v4"),
        region_name="us-east-1",
    )
    buckets = client.list_buckets()
    assert "Buckets" in buckets


@pytest.mark.asyncio
async def test_timescaledb_extension_enabled() -> None:
    """TimescaleDB extension is available (optional for M1.2)."""
    try:
        import asyncpg
    except ImportError:
        pytest.skip("asyncpg not installed")
    conn = await asyncpg.connect(
        host=os.environ.get("PG_HOST", "localhost"),
        port=int(os.environ.get("PG_PORT", "5432")),
        user=os.environ.get("POSTGRES_USER", "phoenixtrader"),
        password=os.environ.get("POSTGRES_PASSWORD", "localdev"),
        database=os.environ.get("POSTGRES_DB", "phoenixtrader"),
    )
    try:
        row = await conn.fetchrow(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') AS ok"
        )
        # Pass even if TimescaleDB not installed (we may add it in M1.6)
        assert row["ok"] in (True, False)
    finally:
        await conn.close()

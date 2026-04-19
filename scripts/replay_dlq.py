#!/usr/bin/env python3
"""Batch replay DLQ messages for a given connector.

Usage:
    python scripts/replay_dlq.py --connector-id <connector_id> [--limit N]
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def replay_dlq(connector_id: str, limit: int) -> None:
    """Batch replay DLQ messages for a connector."""
    database_url = os.getenv("DATABASE_URL", "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    engine = create_async_engine(database_url, echo=False)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with session_factory() as session:
        result = await session.execute(
            text("""
                SELECT id, payload, attempts
                FROM dead_letter_messages
                WHERE connector_id = :cid AND resolved = false
                ORDER BY created_at
                LIMIT :limit
            """),
            {"cid": connector_id, "limit": limit},
        )
        rows = result.all()

    if not rows:
        print(f"No unresolved DLQ messages for connector {connector_id}")
        return

    print(f"Found {len(rows)} unresolved DLQ messages for connector {connector_id}")

    import redis.asyncio as aioredis
    redis_client = aioredis.from_url(redis_url, decode_responses=True)

    stream_key = f"stream:channel:{connector_id}"
    replayed = 0
    failed = 0

    async with session_factory() as session:
        for dlq_id, payload_json, attempts in rows:
            try:
                payload = json.loads(payload_json)
                stream_payload = {k: str(v) for k, v in payload.items()}
                await redis_client.xadd(stream_key, stream_payload)
                await session.execute(
                    text("UPDATE dead_letter_messages SET attempts = :attempts WHERE id = :id"),
                    {"attempts": attempts + 1, "id": str(dlq_id)},
                )
                replayed += 1
                print(f"Replayed {dlq_id} (attempts={attempts + 1})")
            except Exception as exc:
                failed += 1
                print(f"Failed to replay {dlq_id}: {exc}")

        await session.commit()

    await redis_client.aclose()
    await engine.dispose()

    print(f"\nReplay complete: {replayed} replayed, {failed} failed")


def main():
    parser = argparse.ArgumentParser(description="Batch replay DLQ messages")
    parser.add_argument("--connector-id", required=True, help="Connector ID")
    parser.add_argument("--limit", type=int, default=100, help="Max messages to replay (default: 100)")
    args = parser.parse_args()

    asyncio.run(replay_dlq(args.connector_id, args.limit))


if __name__ == "__main__":
    main()

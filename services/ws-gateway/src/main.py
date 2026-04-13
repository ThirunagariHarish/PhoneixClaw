"""
WebSocket gateway entrypoint — runs create_gateway().
"""
import asyncio
import os

import redis.asyncio as aioredis

from .gateway import create_gateway


async def _main():
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_client = aioredis.from_url(redis_url, decode_responses=True)
    await create_gateway(host="0.0.0.0", port=8031, redis_client=redis_client)


if __name__ == "__main__":
    asyncio.run(_main())

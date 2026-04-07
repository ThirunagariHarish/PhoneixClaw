"""H10: Idempotency-Key middleware.

On POST/PUT/PATCH/DELETE requests that carry an `Idempotency-Key` header,
cache the response in Redis for 24h. Repeat calls with the same key return
the cached response without re-executing the handler.

Also exposes a module-level `set_shutting_down()` hook used by the lifespan
handler to reject new work during graceful shutdown.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

_IDEMPOTENCY_TTL = int(os.environ.get("IDEMPOTENCY_TTL_SECONDS", "86400"))
_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_MAX_CACHED_BYTES = 256 * 1024  # don't cache huge responses

_shutting_down = False


def set_shutting_down(flag: bool = True) -> None:
    global _shutting_down
    _shutting_down = flag


def is_shutting_down() -> bool:
    return _shutting_down


async def _get_redis():
    try:
        import redis.asyncio as redis_asyncio
        url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        return redis_asyncio.from_url(url, encoding="utf-8", decode_responses=True)
    except Exception as exc:
        logger.debug("[idempotency] redis unavailable: %s", exc)
        return None


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if _shutting_down:
            return JSONResponse(
                status_code=503,
                content={"error": "server_shutting_down",
                         "detail": "Phoenix API is draining — retry shortly"},
            )

        if request.method not in _METHODS:
            return await call_next(request)

        key: Optional[str] = request.headers.get("idempotency-key")
        if not key:
            return await call_next(request)

        redis = await _get_redis()
        if redis is None:
            return await call_next(request)

        cache_key = f"phoenix:idem:{request.method}:{request.url.path}:{key}"
        try:
            cached = await redis.get(cache_key)
        except Exception:
            cached = None

        if cached:
            try:
                payload = json.loads(cached)
                return JSONResponse(
                    status_code=payload.get("status", 200),
                    content=payload.get("body"),
                    headers={"X-Idempotent-Replay": "true"},
                )
            except Exception:
                pass  # fall through and re-run

        response = await call_next(request)

        # Only cache successful JSON responses below the size limit
        if 200 <= response.status_code < 300:
            body_bytes = b""
            async for chunk in response.body_iterator:
                body_bytes += chunk
            if len(body_bytes) <= _MAX_CACHED_BYTES:
                try:
                    parsed = json.loads(body_bytes.decode("utf-8"))
                    await redis.setex(
                        cache_key,
                        _IDEMPOTENCY_TTL,
                        json.dumps({"status": response.status_code, "body": parsed}),
                    )
                except Exception as exc:
                    logger.debug("[idempotency] cache write skipped: %s", exc)
            return Response(
                content=body_bytes,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response

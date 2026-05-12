"""Read integration secrets (Tiingo, Polygon, OpenAI, etc.) from the DB.

Most services prefer environment variables (set via Helm + SealedSecret) for
keys that must exist at pod startup. But the admin UI lets the operator
update keys from the website at runtime; those land in the `api_keys` table
(see shared/db/models/api_key.py) as encrypted values.

This module provides a single function `get_integration_key(provider, name)`
that checks env vars first (zero-cost, no DB round-trip) and falls back to
the DB. Results are cached in-process for 60 seconds so we don't hammer the
DB on a hot path.

Callers should expect None when the key is not configured anywhere.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

logger = logging.getLogger(__name__)

# Cache: { (provider, name): (value_or_None, expires_at_unix_ts) }
_CACHE: dict[tuple[str, str], tuple[str | None, float]] = {}
_CACHE_TTL_SECONDS = 60
_LOCK = asyncio.Lock()


def _env_var_candidates(provider: str, name: str) -> list[str]:
    """Return env-var names worth checking for this (provider, name)."""
    candidates = [
        name.upper(),
        f"{provider.upper()}_{name.upper()}",
        f"{provider.upper()}_API_KEY",
    ]
    # Common alias: name already includes _API_KEY
    if not name.upper().endswith("_API_KEY"):
        candidates.append(f"{name.upper()}_API_KEY")
    return candidates


async def get_integration_key(provider: str, name: str | None = None) -> str | None:
    """Resolve an integration key by (provider, name).

    Args:
        provider: e.g. "tiingo", "polygon", "openai", "anthropic".
        name: row name in api_keys; defaults to f"{provider}_api_key".

    Returns:
        Plaintext value, or None if not configured.
    """
    if name is None:
        name = f"{provider.lower()}_api_key"
    cache_key = (provider.lower(), name.lower())

    # Env var fast path
    for env_name in _env_var_candidates(provider, name):
        env_val = os.environ.get(env_name)
        if env_val:
            return env_val

    # Cache check
    now = time.time()
    cached = _CACHE.get(cache_key)
    if cached and cached[1] > now:
        return cached[0]

    # DB fallback
    async with _LOCK:
        # Re-check inside the lock to avoid duplicate work
        cached = _CACHE.get(cache_key)
        if cached and cached[1] > now:
            return cached[0]

        value: str | None = None
        try:
            from sqlalchemy import select

            from shared.crypto.credentials import decrypt_value
            from shared.db.engine import get_session
            from shared.db.models.api_key import ApiKeyEntry

            async for db in get_session():
                row = (
                    await db.execute(
                        select(ApiKeyEntry).where(
                            ApiKeyEntry.provider == provider.lower(),
                            ApiKeyEntry.name == name,
                            ApiKeyEntry.is_active.is_(True),
                        ).limit(1)
                    )
                ).scalar_one_or_none()
                if row is not None:
                    try:
                        value = decrypt_value(row.encrypted_value)
                    except Exception as e:
                        logger.warning("Failed to decrypt api_keys row for %s/%s: %s", provider, name, e)
        except Exception as e:
            logger.debug("get_integration_key DB lookup failed for %s/%s: %s", provider, name, e)

        _CACHE[cache_key] = (value, now + _CACHE_TTL_SECONDS)
        return value


def invalidate_cache() -> None:
    """Drop the in-process cache. Call after admin updates a key."""
    _CACHE.clear()

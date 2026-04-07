"""Gamma REST API client (Phase 2, Polymarket v1.0).

Gamma is Polymarket's public metadata API. It serves market lists, market
detail, and the fee schedule. Read-only — no auth required for the
endpoints used here.

Reference: docs/architecture/polymarket-tab.md sections 4.1, 9 (Phase 2),
10 (R-D fee-model drift).

This client is intentionally thin: it speaks HTTP via `httpx.AsyncClient`,
returns JSON dicts/lists, and never holds business logic. Normalization
into `pm_markets` rows happens in Phase 4 (DiscoveryScanner).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://gamma-api.polymarket.com"
DEFAULT_TIMEOUT = 10.0


class GammaClientError(RuntimeError):
    """Raised on non-2xx Gamma responses or transport failures."""


class GammaClient:
    """Async Polymarket Gamma REST client.

    The client owns its `httpx.AsyncClient`. Call `aclose()` (or use as an
    async context manager) to release the underlying connection pool.
    """

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def __aenter__(self) -> "GammaClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        url = f"{self.base_url}{path}"
        try:
            resp = await self._client.get(url, params=params)
        except httpx.HTTPError as e:
            # Never include params in the log message — they may carry IDs
            # but no secrets; still keep the message terse.
            logger.warning("gamma_client transport error path=%s err=%s", path, type(e).__name__)
            raise GammaClientError(f"gamma transport error: {type(e).__name__}") from e

        if resp.status_code >= 400:
            logger.warning("gamma_client http error path=%s status=%d", path, resp.status_code)
            raise GammaClientError(f"gamma http {resp.status_code} for {path}")

        try:
            return resp.json()
        except ValueError as e:
            raise GammaClientError(f"gamma non-json response for {path}") from e

    async def list_markets(
        self,
        *,
        active: bool = True,
        closed: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List markets. Returns the raw Gamma payload as a list of dicts."""
        params: dict[str, Any] = {
            "active": "true" if active else "false",
            "closed": "true" if closed else "false",
            "limit": limit,
            "offset": offset,
        }
        data = await self._get("/markets", params=params)
        if isinstance(data, dict) and "data" in data:
            data = data["data"]
        if not isinstance(data, list):
            raise GammaClientError("gamma /markets returned non-list payload")
        return data

    async def get_market(self, market_id: str) -> dict[str, Any]:
        """Fetch a single market by Gamma id (or condition_id)."""
        data = await self._get(f"/markets/{market_id}")
        if not isinstance(data, dict):
            raise GammaClientError("gamma /markets/{id} returned non-dict payload")
        return data

    async def get_fee_schedule(self) -> dict[str, Any]:
        """Fetch the current fee schedule.

        Polymarket exposes fees per-market on the market object itself, plus
        a coarse account-level fee. This method returns whichever payload
        Gamma serves at `/fees`; if the endpoint 404s the caller is expected
        to fall back to per-market `fee_*` fields. We surface the error so
        the fee cache layer (Phase 6) can decide.
        """
        data = await self._get("/fees")
        if not isinstance(data, dict):
            raise GammaClientError("gamma /fees returned non-dict payload")
        return data

    async def health_check(self) -> dict[str, Any]:
        """Lightweight reachability probe used by `PolymarketBroker.health_check`."""
        try:
            markets = await self.list_markets(limit=1)
        except GammaClientError as e:
            return {"reachable": False, "error": str(e)}
        return {"reachable": True, "sample_count": len(markets)}

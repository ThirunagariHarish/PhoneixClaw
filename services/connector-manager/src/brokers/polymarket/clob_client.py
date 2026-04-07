"""CLOB client wrapper around `py-clob-client` (Phase 2, Polymarket v1.0).

Phase 2 only needs the read/auth surface:
  - construct the underlying client lazily (so the import is optional)
  - expose `get_account()` for balances/allowances
  - expose `health_check()`

Order placement / cancellation lands in a later Polymarket phase. Those
methods are intentionally stubbed with NotImplementedError so the surface
is visible but not callable.

`py-clob-client` is an optional dependency; if it is not installed (CI
without Polygon access), the import fails softly and the wrapper raises a
clear error only when actually invoked. This keeps lint/tests green on
machines that cannot install the SDK.
"""

from __future__ import annotations

import logging
from typing import Any

from .signing import ClobCredentials

logger = logging.getLogger(__name__)

DEFAULT_HOST = "https://clob.polymarket.com"

try:  # pragma: no cover - import guard
    from py_clob_client.client import ClobClient as _UpstreamClobClient  # type: ignore

    _PY_CLOB_AVAILABLE = True
    _PY_CLOB_IMPORT_ERROR: Exception | None = None
except Exception as _e:  # pragma: no cover - import guard
    _UpstreamClobClient = None  # type: ignore
    _PY_CLOB_AVAILABLE = False
    _PY_CLOB_IMPORT_ERROR = _e


class ClobClientError(RuntimeError):
    """Raised on CLOB transport / auth failures, or when the SDK is missing."""


class ClobClient:
    """Thin async-friendly wrapper over py-clob-client.

    py-clob-client is itself synchronous; we keep the wrapper async so the
    rest of the connector can `await` it uniformly. Real calls land in a
    later phase (order paths). For Phase 2 we only construct the client and
    perform the auth round-trip.
    """

    def __init__(
        self,
        creds: ClobCredentials,
        *,
        host: str = DEFAULT_HOST,
    ) -> None:
        self.host = host
        self._creds = creds
        self._client: Any | None = None

    @staticmethod
    def is_available() -> bool:
        return _PY_CLOB_AVAILABLE

    def _ensure_sdk(self) -> None:
        if not _PY_CLOB_AVAILABLE:
            raise ClobClientError(
                "py-clob-client is not installed; install it to enable PolymarketBroker"
            )

    async def connect(self) -> None:
        """Construct the upstream client. Does not log credential material."""
        self._ensure_sdk()
        if self._client is not None:
            return
        try:
            # Upstream constructor signature (positional kwargs vary by version):
            #   ClobClient(host, key=private_key, chain_id=...)
            self._client = _UpstreamClobClient(  # type: ignore[misc]
                self.host,
                key=self._creds.private_key,
                chain_id=self._creds.chain_id,
            )
        except Exception as e:
            # Redact: never include the private key in the message.
            raise ClobClientError(f"clob connect failed: {type(e).__name__}") from e
        logger.info("clob_client connected host=%s creds=%s", self.host, self._creds.redacted())

    async def disconnect(self) -> None:
        self._client = None

    async def get_account(self) -> dict[str, Any]:
        """Return account summary. Phase 2 returns a minimal placeholder.

        Real balance/allowance fetches land alongside order paths in a later
        phase, where the upstream `get_balance_allowance()` call will be
        wrapped in the connector's circuit breaker.
        """
        self._ensure_sdk()
        if self._client is None:
            raise ClobClientError("clob client not connected")
        return {
            "venue": "polymarket",
            "host": self.host,
            "chain_id": self._creds.chain_id,
            "connected": True,
        }

    async def health_check(self) -> dict[str, Any]:
        """Report SDK availability and connection state. No network call yet."""
        return {
            "sdk_available": _PY_CLOB_AVAILABLE,
            "connected": self._client is not None,
            "host": self.host,
            "import_error": (
                None if _PY_CLOB_IMPORT_ERROR is None else type(_PY_CLOB_IMPORT_ERROR).__name__
            ),
        }

    # ------------------------------------------------------------------
    # Order surface — stubbed for Phase 2; implemented in a later phase.
    # ------------------------------------------------------------------
    async def submit_order(self, *_a, **_kw) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError("CLOB order submission lands in a later Polymarket phase")

    async def cancel_order(self, *_a, **_kw) -> dict[str, Any]:  # pragma: no cover
        raise NotImplementedError("CLOB order cancellation lands in a later Polymarket phase")

    async def get_positions(self) -> list[dict[str, Any]]:  # pragma: no cover
        raise NotImplementedError("CLOB positions land in a later Polymarket phase")

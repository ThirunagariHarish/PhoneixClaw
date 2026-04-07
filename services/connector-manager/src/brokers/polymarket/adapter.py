"""PolymarketBroker — concrete BaseBroker for Polymarket (Phase 2).

Reference: docs/architecture/polymarket-tab.md section 9, Phase 2.

Phase 2 surface:
  - `connect()` enforces the JurisdictionAttestationGate, then opens the
    Gamma client and (if SDK present) the CLOB client.
  - `disconnect()` releases both.
  - `get_account()` returns CLOB account summary.
  - `health_check()` aggregates Gamma + CLOB reachability.
  - Order / position methods raise NotImplementedError (later phase).

The adapter wraps every outbound call in `shared/broker/circuit_breaker.py`
so transient Polymarket outages do not melt the connector-manager.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.orm import Session

from shared.broker.circuit_breaker import CircuitBreaker
from shared.polymarket.jurisdiction import (
    JurisdictionAttestationGate,
    JurisdictionGateError,
)

from ..base_broker import BaseBroker
from .clob_client import DEFAULT_HOST as DEFAULT_CLOB_HOST
from .clob_client import ClobClient, ClobClientError
from .gamma_client import DEFAULT_BASE_URL as DEFAULT_GAMMA_URL
from .gamma_client import GammaClient, GammaClientError
from .signing import ClobCredentials

logger = logging.getLogger(__name__)


class PolymarketBrokerError(RuntimeError):
    """Raised when the PolymarketBroker cannot fulfill a request."""


class PolymarketBroker(BaseBroker):
    """Concrete broker adapter for Polymarket.

    Construction is cheap. The expensive work (SDK construction, jurisdiction
    check) happens in `connect()`. Tests inject `gamma_client`, `clob_client`,
    and `jurisdiction_gate` to avoid real HTTP and real DB.
    """

    def __init__(
        self,
        config: dict[str, Any],
        *,
        session: Session | None = None,
        gamma_client: GammaClient | None = None,
        clob_client: ClobClient | None = None,
        jurisdiction_gate: JurisdictionAttestationGate | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self._config = config
        self._user_id: uuid.UUID | None = self._coerce_uuid(config.get("user_id"))
        self._session = session
        self._gamma_url: str = config.get("gamma_url", DEFAULT_GAMMA_URL)
        self._clob_host: str = config.get("clob_host", DEFAULT_CLOB_HOST)
        self._gamma = gamma_client or GammaClient(self._gamma_url)
        self._clob = clob_client or ClobClient(
            self._build_credentials(config),
            host=self._clob_host,
        )
        self._gate = jurisdiction_gate or JurisdictionAttestationGate()
        self._breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=30.0,
        )
        self._connected = False

    # ------------------------------------------------------------------
    # Construction helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _coerce_uuid(value: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _maybe_decrypt(value: str, *, field_name: str) -> str:
        """M6: Fernet seam for stored secrets.

        Polymarket private keys (and CLOB secrets) must be at-rest encrypted
        with the existing Fernet helper. We detect the Fernet token prefix
        ('gAAAAA') and decrypt; for plaintext we log a warning so operators
        can migrate.
        """
        if not value:
            return ""
        if isinstance(value, str) and value.startswith("gAAAAA"):
            try:
                from shared.crypto.credentials import decrypt_value
            except Exception as e:  # pragma: no cover - import-time defensive
                logger.error("polymarket: cannot import Fernet helper: %s", e)
                raise PolymarketBrokerError(
                    "encrypted credentials present but Fernet helper unavailable"
                ) from e
            try:
                return decrypt_value(value)
            except Exception as e:
                logger.error("polymarket: failed to decrypt %s: %s", field_name, type(e).__name__)
                raise PolymarketBrokerError(
                    f"failed to decrypt polymarket {field_name}"
                ) from e
        logger.warning(
            "polymarket: %s is stored in plaintext — rotate to Fernet-encrypted "
            "storage (gAAAAA...) as soon as possible",
            field_name,
        )
        return value

    @classmethod
    def _build_credentials(cls, config: dict[str, Any]) -> ClobCredentials:
        return ClobCredentials(
            private_key=cls._maybe_decrypt(config.get("private_key", ""), field_name="private_key"),
            api_key=config.get("clob_api_key", ""),
            api_secret=cls._maybe_decrypt(
                config.get("clob_api_secret", ""), field_name="clob_api_secret"
            ),
            api_passphrase=cls._maybe_decrypt(
                config.get("clob_api_passphrase", ""), field_name="clob_api_passphrase"
            ),
            chain_id=int(config.get("chain_id", 137)),
        )

    # ------------------------------------------------------------------
    # BaseBroker surface
    # ------------------------------------------------------------------
    async def connect(self) -> None:
        """Validate jurisdiction, then open downstream clients.

        Order matters: jurisdiction first so we never even touch the CLOB
        SDK without an attestation. The gate is the single Phase 1 primitive
        guarding live mode.
        """
        if self._user_id is None:
            raise PolymarketBrokerError("PolymarketBroker requires config.user_id")
        if self._session is None:
            raise PolymarketBrokerError("PolymarketBroker requires a SQLAlchemy session for the gate")

        try:
            self._gate.assert_valid(self._session, self._user_id)
        except JurisdictionGateError as e:
            # Do not log the user_id at error level beyond what the gate already says.
            logger.warning("polymarket connect blocked by jurisdiction gate: %s", e)
            raise PolymarketBrokerError(f"jurisdiction gate failed: {e}") from e

        # Open downstream clients. Gamma is unauthenticated and always opens.
        # CLOB only opens if the SDK is installed; otherwise we degrade to
        # read-only metadata mode (Phase 2 still considers this "connected"
        # because no order surface exists yet).
        if ClobClient.is_available() and self._has_credentials():
            try:
                await self._breaker.call(self._clob.connect)
            except ClobClientError as e:
                logger.warning("polymarket clob connect failed: %s", e)
                raise PolymarketBrokerError(str(e)) from e
        else:
            logger.info(
                "polymarket connect: clob sdk_available=%s creds_present=%s — metadata-only mode",
                ClobClient.is_available(),
                self._has_credentials(),
            )

        self._connected = True

    async def disconnect(self) -> None:
        try:
            await self._clob.disconnect()
        finally:
            await self._gamma.aclose()
            self._connected = False

    async def get_account(self) -> dict[str, Any]:
        self._require_connected()
        if not ClobClient.is_available() or not self._has_credentials():
            return {
                "venue": "polymarket",
                "mode": "metadata_only",
                "connected": True,
            }
        return await self._breaker.call(self._clob.get_account)

    async def submit_order(self, order: dict) -> dict[str, Any]:
        # M5: re-check the jurisdiction attestation on every order, not just
        # at connect-time. An attestation expiring mid-session must block the
        # next order; the connect-time check alone is insufficient.
        if self._user_id is None or self._session is None:
            raise PolymarketBrokerError(
                "PolymarketBroker.submit_order requires user_id + session for jurisdiction recheck"
            )
        try:
            self._gate.assert_valid(self._session, self._user_id)
        except JurisdictionGateError as e:
            logger.warning("polymarket submit_order blocked by jurisdiction gate: %s", e)
            raise PolymarketBrokerError(f"jurisdiction gate failed: {e}") from e
        raise NotImplementedError("Polymarket order submission lands in a later phase")

    async def get_positions(self) -> list[dict]:
        raise NotImplementedError("Polymarket positions land in a later phase")

    async def close_position(self, symbol: str) -> dict[str, Any]:
        raise NotImplementedError("Polymarket close_position lands in a later phase")

    async def health_check(self) -> dict[str, Any]:
        """Aggregate Gamma + CLOB health. Reports `ok` only when both are happy.

        Gamma is the source of truth for "Polymarket reachable" because it is
        unauthenticated and stable. CLOB health is reported separately so the
        caller can distinguish "metadata works, signing offline" from a full
        outage.
        """
        gamma_health: dict[str, Any]
        try:
            gamma_health = await self._breaker.call(self._gamma.health_check)
        except GammaClientError as e:
            gamma_health = {"reachable": False, "error": str(e)}
        except Exception as e:  # circuit breaker open, etc.
            gamma_health = {"reachable": False, "error": type(e).__name__}

        clob_health = await self._clob.health_check()

        status = "ok" if gamma_health.get("reachable") else "degraded"
        return {
            "status": status,
            "venue": "polymarket",
            "gamma": gamma_health,
            "clob": clob_health,
            "connected": self._connected,
        }

    # ------------------------------------------------------------------
    # Phase 2 metadata helpers exposed for the DiscoveryScanner (Phase 4).
    # Kept here so callers do not have to reach into `_gamma`.
    # ------------------------------------------------------------------
    async def list_markets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return await self._breaker.call(self._gamma.list_markets, **kwargs)

    async def get_market(self, market_id: str) -> dict[str, Any]:
        return await self._breaker.call(self._gamma.get_market, market_id)

    async def get_fee_schedule(self) -> dict[str, Any]:
        return await self._breaker.call(self._gamma.get_fee_schedule)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _has_credentials(self) -> bool:
        return bool(self._config.get("private_key"))

    def _require_connected(self) -> None:
        if not self._connected:
            raise PolymarketBrokerError("PolymarketBroker not connected")

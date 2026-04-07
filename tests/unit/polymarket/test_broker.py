"""Unit tests for PolymarketBroker, GammaClient, and ClobClient (Phase 2).

These tests mock all HTTP via httpx.MockTransport and stub the
JurisdictionAttestationGate so no real network or DB is required.

Reference: docs/architecture/polymarket-tab.md Phase 2 DoD.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from services.connector_manager.src.brokers.polymarket.adapter import (
    PolymarketBroker,
    PolymarketBrokerError,
)
from services.connector_manager.src.brokers.polymarket.clob_client import (
    ClobClient,
    ClobClientError,
)
from services.connector_manager.src.brokers.polymarket.gamma_client import (
    GammaClient,
    GammaClientError,
)
from services.connector_manager.src.brokers.polymarket.signing import ClobCredentials
from shared.polymarket.jurisdiction import (
    AttestationState,
    JurisdictionAttestationGate,
    JurisdictionGateError,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------
class _StubGate(JurisdictionAttestationGate):
    """JurisdictionAttestationGate that returns a preset state without DB."""

    def __init__(self, *, valid: bool, reason: str = "ok") -> None:
        super().__init__()
        self._state = AttestationState(valid=valid, reason=reason)

    def evaluate(self, session, user_id):  # type: ignore[override]
        return self._state

    def assert_valid(self, session, user_id):  # type: ignore[override]
        if not self._state.valid:
            raise JurisdictionGateError(self._state.reason)
        return self._state


def _gamma_with_handler(handler) -> GammaClient:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return GammaClient(base_url="https://gamma.test", client=client)


def _stub_clob() -> ClobClient:
    """ClobClient that pretends the SDK is missing — Phase 2 metadata-only path."""
    creds = ClobCredentials(
        private_key="",
        api_key="",
        api_secret="",
        api_passphrase="",
    )
    return ClobClient(creds, host="https://clob.test")


# ---------------------------------------------------------------------------
# GammaClient
# ---------------------------------------------------------------------------
class TestGammaClient:
    @pytest.mark.asyncio
    async def test_list_markets_returns_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/markets"
            assert request.url.params["limit"] == "5"
            return httpx.Response(200, json=[{"id": "m1"}, {"id": "m2"}])

        async with _gamma_with_handler(handler) as gamma:
            markets = await gamma.list_markets(limit=5)

        assert len(markets) == 2
        assert markets[0]["id"] == "m1"

    @pytest.mark.asyncio
    async def test_list_markets_unwraps_data_envelope(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"data": [{"id": "x"}]})

        async with _gamma_with_handler(handler) as gamma:
            markets = await gamma.list_markets()
        assert markets == [{"id": "x"}]

    @pytest.mark.asyncio
    async def test_get_market_round_trip(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/markets/abc"
            return httpx.Response(200, json={"id": "abc", "question": "Q?"})

        async with _gamma_with_handler(handler) as gamma:
            market = await gamma.get_market("abc")
        assert market["question"] == "Q?"

    @pytest.mark.asyncio
    async def test_http_error_becomes_gamma_error(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="boom")

        async with _gamma_with_handler(handler) as gamma:
            with pytest.raises(GammaClientError):
                await gamma.list_markets()

    @pytest.mark.asyncio
    async def test_health_check_reachable(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "m1"}])

        async with _gamma_with_handler(handler) as gamma:
            health = await gamma.health_check()
        assert health["reachable"] is True
        assert health["sample_count"] == 1

    @pytest.mark.asyncio
    async def test_health_check_unreachable(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        async with _gamma_with_handler(handler) as gamma:
            health = await gamma.health_check()
        assert health["reachable"] is False
        assert "error" in health

    @pytest.mark.asyncio
    async def test_non_list_markets_payload_raises(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"oops": True})

        async with _gamma_with_handler(handler) as gamma:
            with pytest.raises(GammaClientError):
                await gamma.list_markets()


# ---------------------------------------------------------------------------
# ClobClient (SDK-absence path)
# ---------------------------------------------------------------------------
class TestClobClient:
    def test_redacted_credentials_have_no_secrets(self) -> None:
        creds = ClobCredentials(
            private_key="0xdeadbeef",
            api_key="key",
            api_secret="secret",
            api_passphrase="pass",
        )
        red = creds.redacted()
        assert "0xdeadbeef" not in str(red)
        assert "secret" not in str(red).replace("api_secret", "")
        assert red["chain_id"] == "137"

    @pytest.mark.asyncio
    async def test_health_check_reports_sdk_state(self) -> None:
        client = _stub_clob()
        health = await client.health_check()
        assert "sdk_available" in health
        assert health["connected"] is False
        assert health["host"] == "https://clob.test"

    @pytest.mark.asyncio
    async def test_get_account_requires_connection_or_sdk(self) -> None:
        client = _stub_clob()
        # Without SDK installed _ensure_sdk raises immediately. With SDK
        # installed but no connect(), it must still raise. Either is fine.
        with pytest.raises(ClobClientError):
            await client.get_account()

    @pytest.mark.asyncio
    async def test_order_methods_are_stubbed(self) -> None:
        client = _stub_clob()
        with pytest.raises(NotImplementedError):
            await client.submit_order()


# ---------------------------------------------------------------------------
# PolymarketBroker
# ---------------------------------------------------------------------------
class TestPolymarketBroker:
    def _make_broker(
        self,
        *,
        gate_valid: bool = True,
        gamma_handler=None,
        with_session: bool = True,
        with_user: bool = True,
    ) -> PolymarketBroker:
        if gamma_handler is None:
            def gamma_handler(_req: httpx.Request) -> httpx.Response:
                return httpx.Response(200, json=[{"id": "m1"}])

        gamma = _gamma_with_handler(gamma_handler)
        clob = _stub_clob()
        gate = _StubGate(valid=gate_valid, reason="ok" if gate_valid else "expired")
        config: dict[str, Any] = {}
        if with_user:
            config["user_id"] = uuid.uuid4()
        return PolymarketBroker(
            config,
            session=object() if with_session else None,
            gamma_client=gamma,
            clob_client=clob,
            jurisdiction_gate=gate,
        )

    @pytest.mark.asyncio
    async def test_connect_requires_user_id(self) -> None:
        broker = self._make_broker(with_user=False)
        with pytest.raises(PolymarketBrokerError, match="user_id"):
            await broker.connect()

    @pytest.mark.asyncio
    async def test_connect_requires_session(self) -> None:
        broker = self._make_broker(with_session=False)
        with pytest.raises(PolymarketBrokerError, match="session"):
            await broker.connect()

    @pytest.mark.asyncio
    async def test_connect_blocked_when_jurisdiction_invalid(self) -> None:
        broker = self._make_broker(gate_valid=False)
        with pytest.raises(PolymarketBrokerError, match="jurisdiction"):
            await broker.connect()

    @pytest.mark.asyncio
    async def test_connect_succeeds_in_metadata_only_mode(self) -> None:
        broker = self._make_broker()
        await broker.connect()
        # No private_key in config and SDK may be missing — broker should
        # still report connected for the metadata path.
        account = await broker.get_account()
        assert account["venue"] == "polymarket"
        assert account["mode"] == "metadata_only"
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_health_check_aggregates_gamma_and_clob(self) -> None:
        broker = self._make_broker()
        await broker.connect()
        health = await broker.health_check()
        assert health["status"] == "ok"
        assert health["venue"] == "polymarket"
        assert health["gamma"]["reachable"] is True
        assert "clob" in health
        await broker.disconnect()

    @pytest.mark.asyncio
    async def test_health_check_degraded_when_gamma_down(self) -> None:
        def handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(500)

        broker = self._make_broker(gamma_handler=handler)
        await broker.connect()
        health = await broker.health_check()
        assert health["status"] == "degraded"
        assert health["gamma"]["reachable"] is False

    @pytest.mark.asyncio
    async def test_list_markets_proxies_to_gamma(self) -> None:
        seen: dict[str, Any] = {}

        def handler(req: httpx.Request) -> httpx.Response:
            seen["path"] = req.url.path
            return httpx.Response(200, json=[{"id": "m9"}])

        broker = self._make_broker(gamma_handler=handler)
        await broker.connect()
        markets = await broker.list_markets(limit=1)
        assert markets[0]["id"] == "m9"
        assert seen["path"] == "/markets"

    @pytest.mark.asyncio
    async def test_order_surface_not_implemented(self) -> None:
        broker = self._make_broker()
        await broker.connect()
        with pytest.raises(NotImplementedError):
            await broker.submit_order({})
        with pytest.raises(NotImplementedError):
            await broker.get_positions()
        with pytest.raises(NotImplementedError):
            await broker.close_position("x")

    @pytest.mark.asyncio
    async def test_get_account_requires_connect(self) -> None:
        broker = self._make_broker()
        with pytest.raises(PolymarketBrokerError, match="not connected"):
            await broker.get_account()

    @pytest.mark.asyncio
    async def test_submit_order_rechecks_jurisdiction_mid_session(self) -> None:
        # M5: connect succeeds with a valid gate, but if the attestation is
        # invalidated mid-session (gate starts returning invalid), the next
        # submit_order must be blocked *before* reaching the stubbed venue
        # path (which would otherwise raise NotImplementedError).
        class _FlippingGate(_StubGate):
            def __init__(self):
                super().__init__(valid=True)
                self.calls = 0

            def assert_valid(self, session, user_id):  # type: ignore[override]
                self.calls += 1
                if self.calls > 1:
                    raise JurisdictionGateError("expired")
                return self._state

        gate = _FlippingGate()

        def gamma_handler(_req: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=[{"id": "m1"}])

        broker = PolymarketBroker(
            {"user_id": uuid.uuid4()},
            session=object(),
            gamma_client=_gamma_with_handler(gamma_handler),
            clob_client=_stub_clob(),
            jurisdiction_gate=gate,
        )
        await broker.connect()
        with pytest.raises(PolymarketBrokerError, match="jurisdiction"):
            await broker.submit_order({"qty_shares": 1, "limit_price": 0.5})

    def test_build_credentials_decrypts_fernet_token(self, monkeypatch) -> None:
        # M6: a Fernet-shaped private_key (gAAAAA prefix) must be decrypted
        # via shared.crypto.credentials before being passed to ClobCredentials.
        called: dict[str, str] = {}

        def fake_decrypt(value: str) -> str:
            called["got"] = value
            return "0xdecrypted"

        import shared.crypto.credentials as cred_mod
        monkeypatch.setattr(cred_mod, "decrypt_value", fake_decrypt, raising=True)

        creds = PolymarketBroker._build_credentials(
            {"private_key": "gAAAAAsomething", "clob_api_key": "k"}
        )
        assert creds.private_key == "0xdecrypted"
        assert called["got"] == "gAAAAAsomething"

    def test_build_credentials_plaintext_still_accepted_with_warning(
        self, caplog
    ) -> None:
        caplog.set_level("WARNING")
        creds = PolymarketBroker._build_credentials(
            {"private_key": "0xplaintext", "clob_api_key": "k"}
        )
        assert creds.private_key == "0xplaintext"
        assert any("plaintext" in r.message for r in caplog.records)

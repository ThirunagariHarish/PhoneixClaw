"""Tests for Alpaca broker adapter: symbol formatting, paper mode, auth errors, and executor health checks.

Covers all tickers from the failing trades CSV:
SPX, AMD, IWM, VIX, GLD, SLV, AAPL
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from shared.broker.alpaca_adapter import (
    ALPACA_LIVE_BASE,
    ALPACA_TRADE_BASE,
    AlpacaAuthError,
    AlpacaBrokerAdapter,
    AlpacaOrderError,
)

# ---------------------------------------------------------------------------
# Symbol formatting
# ---------------------------------------------------------------------------

class TestFormatOptionSymbol:
    """Verify OCC symbol generation for every ticker in the failing trades CSV."""

    @pytest.fixture
    def adapter(self):
        return AlpacaBrokerAdapter(api_key="test", secret_key="test", paper=True)

    @pytest.mark.parametrize(
        "ticker, expiration, option_type, strike, expected",
        [
            ("SPX", "2026-02-24", "CALL", 6895, "SPXW260224C06895000"),
            ("SPX", "2026-02-24", "CALL", 6875, "SPXW260224C06875000"),
            ("SPX", "2026-02-24", "CALL", 6900, "SPXW260224C06900000"),
            ("SPX", "2026-02-24", "PUT", 6895, "SPXW260224P06895000"),
            ("NDX", "2026-03-20", "CALL", 20000, "NDXP260320C20000000"),
            ("AMD", "2026-02-24", "CALL", 220, "AMD260224C00220000"),
            ("AMD", "2026-02-24", "CALL", 320, "AMD260224C00320000"),
            ("IWM", "2026-02-24", "CALL", 250, "IWM260224C00250000"),
            ("VIX", "2026-03-20", "CALL", 20, "VIX260320C00020000"),
            ("GLD", "2026-02-24", "CALL", 485, "GLD260224C00485000"),
            ("SLV", "2026-02-24", "CALL", 90, "SLV260224C00090000"),
            ("AAPL", "2026-02-20", "CALL", 190, "AAPL260220C00190000"),
            ("SPY", "2026-02-24", "PUT", 580, "SPY260224P00580000"),
        ],
    )
    def test_symbol_format(self, adapter, ticker, expiration, option_type, strike, expected):
        result = adapter.format_option_symbol(ticker, expiration, option_type, strike)
        assert result == expected, f"Expected {expected}, got {result}"

    def test_spx_maps_to_spxw(self, adapter):
        symbol = adapter.format_option_symbol("SPX", "2026-02-24", "CALL", 6895)
        assert symbol.startswith("SPXW"), f"SPX should map to SPXW, got {symbol}"

    def test_ndx_maps_to_ndxp(self, adapter):
        symbol = adapter.format_option_symbol("NDX", "2026-03-20", "CALL", 20000)
        assert symbol.startswith("NDXP"), f"NDX should map to NDXP, got {symbol}"

    def test_regular_ticker_unchanged(self, adapter):
        symbol = adapter.format_option_symbol("AAPL", "2026-02-20", "CALL", 190)
        assert symbol.startswith("AAPL"), f"AAPL should stay AAPL, got {symbol}"

    def test_strike_with_decimals(self, adapter):
        symbol = adapter.format_option_symbol("SPY", "2026-02-24", "CALL", 580.5)
        assert symbol == "SPY260224C00580500"


# ---------------------------------------------------------------------------
# Paper mode / base URL resolution
# ---------------------------------------------------------------------------

class TestPaperMode:
    def test_paper_true_uses_paper_url(self):
        adapter = AlpacaBrokerAdapter(api_key="k", secret_key="s", paper=True)
        assert adapter.base_url == ALPACA_TRADE_BASE
        assert adapter.is_paper is True

    def test_paper_false_uses_live_url(self):
        adapter = AlpacaBrokerAdapter(api_key="k", secret_key="s", paper=False)
        assert adapter.base_url == ALPACA_LIVE_BASE
        assert adapter.is_paper is False

    def test_paper_none_defaults_from_config(self):
        with patch("shared.broker.alpaca_adapter.config") as mock_config:
            mock_config.broker.api_key = "k"
            mock_config.broker.secret_key = "s"
            mock_config.broker.paper = True
            adapter = AlpacaBrokerAdapter(paper=None)
            assert adapter.is_paper is True
            assert adapter.base_url == ALPACA_TRADE_BASE


# ---------------------------------------------------------------------------
# Error handling and auth errors
# ---------------------------------------------------------------------------

class TestErrorHandling:
    @pytest.fixture
    def adapter(self):
        return AlpacaBrokerAdapter(api_key="test", secret_key="test", paper=True)

    def test_401_raises_auth_error(self, adapter):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.json.return_value = {"message": "request is not authorized"}
        with pytest.raises(AlpacaAuthError) as exc_info:
            adapter._raise_with_detail(resp, symbol="SPX260224C06895000")
        assert "401" in str(exc_info.value)
        assert "PAPER" in str(exc_info.value)
        assert "paper-api.alpaca.markets" in str(exc_info.value)

    def test_403_raises_auth_error(self, adapter):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 403
        resp.json.return_value = {"message": "forbidden"}
        with pytest.raises(AlpacaAuthError):
            adapter._raise_with_detail(resp, symbol="TEST")

    def test_422_raises_order_error_not_auth(self, adapter):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 422
        resp.json.return_value = {"message": "insufficient buying power"}
        with pytest.raises(AlpacaOrderError) as exc_info:
            adapter._raise_with_detail(resp, symbol="TEST")
        assert not isinstance(exc_info.value, AlpacaAuthError)

    def test_200_no_error(self, adapter):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        adapter._raise_with_detail(resp, symbol="TEST")

    def test_live_mode_error_shows_live_url(self):
        adapter = AlpacaBrokerAdapter(api_key="k", secret_key="s", paper=False)
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.json.return_value = {"message": "unauthorized"}
        with pytest.raises(AlpacaAuthError) as exc_info:
            adapter._raise_with_detail(resp, symbol="AMD260224C00220000")
        msg = str(exc_info.value)
        assert "LIVE" in msg
        assert "api.alpaca.markets" in msg
        assert "AMD260224C00220000" in msg

    def test_error_includes_symbol(self, adapter):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.json.return_value = {"message": "bad request"}
        with pytest.raises(AlpacaOrderError) as exc_info:
            adapter._raise_with_detail(resp, symbol="SPXW260224C06875000")
        assert "SPXW260224C06875000" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Executor broker health check and auth-aware error handling
# ---------------------------------------------------------------------------

class TestExecutorHealthCheck:
    @pytest.fixture
    def mock_broker(self):
        broker = AsyncMock()
        broker.base_url = ALPACA_TRADE_BASE
        broker.is_paper = True
        broker.format_option_symbol = MagicMock(return_value="SPXW260224C06895000")
        return broker

    @pytest.mark.asyncio
    async def test_auth_error_rejects_trade_immediately(self):
        """AlpacaAuthError should reject the trade, not trip the circuit breaker."""
        from shared.broker.circuit_breaker import CircuitBreaker

        cb = CircuitBreaker(
            failure_threshold=5, recovery_timeout=60.0,
            excluded_exceptions=(AlpacaAuthError,),
        )
        initial_failure_count = cb._failure_count

        broker = AsyncMock()
        broker.base_url = ALPACA_TRADE_BASE
        broker.is_paper = True
        broker.get_account = AsyncMock(return_value={
            "buying_power": 100000, "cash": 100000,
            "equity": 100000, "portfolio_value": 100000,
        })
        broker.place_limit_order = AsyncMock(side_effect=AlpacaAuthError("Alpaca 401: unauthorized"))
        broker.format_option_symbol = MagicMock(return_value="SPXW260224C06895000")

        from services.trade_executor.src.executor import TradeExecutorService

        service = TradeExecutorService(broker=None)
        service._broker_cache = {"test-account": broker}
        service._verified_accounts = {"test-account"}
        service._circuit_breaker = cb
        service.producer = AsyncMock()

        trade = {
            "trade_id": "test-123",
            "user_id": "user-1",
            "trading_account_id": "test-account",
            "ticker": "SPX",
            "action": "BUY",
            "strike": 6895,
            "option_type": "CALL",
            "price": 2.60,
            "quantity": "1",
            "expiration": "2026-02-24",
            "source": "discord",
        }

        with patch.object(service, "_publish_result", new_callable=AsyncMock) as mock_publish, \
             patch.object(service, "_resolve_broker", return_value=broker):
            await service._handle_trade(trade, {})

            mock_publish.assert_called_once()
            call_args = mock_publish.call_args
            assert call_args[0][1] == "REJECTED"
            assert "401" in (call_args[1].get("error_message") or call_args[0][2] or "")

        assert cb._failure_count == initial_failure_count, \
            "Circuit breaker should NOT have been tripped by auth errors"

    @pytest.mark.asyncio
    async def test_verify_broker_catches_auth_failure(self):
        from services.trade_executor.src.executor import TradeExecutorService

        service = TradeExecutorService()

        broker = AsyncMock()
        broker.base_url = ALPACA_TRADE_BASE
        broker.is_paper = True
        broker.get_account = AsyncMock(side_effect=AlpacaAuthError("Alpaca 401: unauthorized"))

        account = MagicMock()
        account.paper_mode = True
        account.display_name = "Test Paper"

        await service._verify_broker("acc-123", broker, account)

        assert "acc-123" in service._failed_accounts
        assert "acc-123" not in service._verified_accounts
        assert "401" in service._failed_accounts["acc-123"]

    @pytest.mark.asyncio
    async def test_verify_broker_succeeds(self):
        from services.trade_executor.src.executor import TradeExecutorService

        service = TradeExecutorService()

        broker = AsyncMock()
        broker.base_url = ALPACA_TRADE_BASE
        broker.is_paper = True
        broker.get_account = AsyncMock(return_value={
            "buying_power": 100000, "cash": 50000, "equity": 100000, "portfolio_value": 100000,
        })

        account = MagicMock()
        account.paper_mode = True
        account.display_name = "Test Paper"

        await service._verify_broker("acc-456", broker, account)

        assert "acc-456" in service._verified_accounts
        assert "acc-456" not in service._failed_accounts

    @pytest.mark.asyncio
    async def test_failed_account_rejects_subsequent_trades(self):
        from services.trade_executor.src.executor import TradeExecutorService

        error_msg = "Broker auth FAILED (PAPER): check API keys"
        service = TradeExecutorService()
        service._failed_accounts = {
            "bad-account:paper": error_msg,
        }
        service._broker_cache = {"bad-account:paper": AsyncMock()}
        service.producer = AsyncMock()

        mock_broker = service._broker_cache["bad-account:paper"]

        trade = {
            "trade_id": "test-789",
            "user_id": "user-1",
            "trading_account_id": "bad-account",
            "ticker": "SPX",
            "action": "BUY",
            "strike": 6895,
            "option_type": "CALL",
            "price": 2.60,
            "quantity": "1",
            "expiration": "2026-02-24",
            "source": "discord",
        }

        async def mock_resolve(t):
            t["_broker_failed"] = error_msg
            t["_broker_cache_key"] = "bad-account:paper"
            return mock_broker

        with patch.object(service, "_publish_result", new_callable=AsyncMock) as mock_publish, \
             patch.object(service, "_resolve_broker", side_effect=mock_resolve):
            await service._handle_trade(trade, {})

            mock_publish.assert_called_once()
            assert mock_publish.call_args[0][1] == "REJECTED"
            assert "auth FAILED" in (
                mock_publish.call_args[1].get("error_message", "") or ""
            )

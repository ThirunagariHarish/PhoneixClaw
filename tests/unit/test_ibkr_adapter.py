"""Unit tests for IBKR broker adapter."""

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock ib_insync before importing adapter
sys.modules["ib_insync"] = MagicMock()

from shared.broker.ibkr_adapter import BrokerAPIError, IBKRBrokerAdapter


class TestIBKRAdapter:
    """Test IBKR adapter with mocked ib_insync.IB."""

    @pytest.fixture
    def adapter(self):
        return IBKRBrokerAdapter(host="localhost", port=7497, account_id="DU12345")

    @pytest.fixture
    def mock_ib(self):
        """Mock ib_insync.IB instance."""
        ib = MagicMock()
        ib.isConnected.return_value = True
        ib.connectAsync = AsyncMock()
        ib.disconnect = MagicMock()
        return ib

    @pytest.mark.asyncio
    async def test_ensure_connected_success(self, adapter, mock_ib):
        """Test successful connection to IB Gateway."""
        with patch("shared.broker.ibkr_adapter.IB", return_value=mock_ib):
            ib = await adapter._ensure_connected()
            assert ib == mock_ib
            mock_ib.connectAsync.assert_called_once_with("localhost", 7497, clientId=1, timeout=30.0)
            assert adapter._connected is True

    @pytest.mark.asyncio
    async def test_ensure_connected_failure(self, adapter):
        """Test connection failure with retry."""
        mock_ib = MagicMock()
        mock_ib.connectAsync = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("shared.broker.ibkr_adapter.IB", return_value=mock_ib):
            with pytest.raises(BrokerAPIError) as exc_info:
                await adapter._ensure_connected()
            assert "Failed to connect to IBKR" in str(exc_info.value)
            assert adapter._reconnect_attempts == 1

    @pytest.mark.asyncio
    async def test_place_limit_order(self, adapter, mock_ib):
        """Test place limit order."""
        mock_trade = MagicMock()
        mock_trade.order.orderId = 12345
        mock_ib.placeOrder = MagicMock(return_value=mock_trade)

        adapter._ib = mock_ib

        order_id = await adapter.place_limit_order("SPY260616C00600000", 1, "buy", 3.50)
        assert order_id == "12345"
        mock_ib.placeOrder.assert_called_once()

    @pytest.mark.asyncio
    async def test_place_bracket_order(self, adapter, mock_ib):
        """Test place bracket order."""
        mock_trade = MagicMock()
        mock_trade.order.orderId = 12346
        mock_ib.placeOrder = MagicMock(return_value=mock_trade)

        adapter._ib = mock_ib

        order_id = await adapter.place_bracket_order("AAPL", 10, "buy", 180.0, 190.0, 170.0)
        assert order_id == "12346"
        # Should call placeOrder 3 times (parent + TP + SL)
        assert mock_ib.placeOrder.call_count == 3

    @pytest.mark.asyncio
    async def test_cancel_order(self, adapter, mock_ib):
        """Test cancel order."""
        mock_ib.cancelOrder = MagicMock()
        adapter._ib = mock_ib

        result = await adapter.cancel_order("12345")
        assert result is True
        mock_ib.cancelOrder.assert_called_once_with(12345)

    @pytest.mark.asyncio
    async def test_get_order_status(self, adapter, mock_ib):
        """Test get order status."""
        mock_trade = MagicMock()
        mock_trade.order.orderId = 12345
        mock_trade.orderStatus.status = "Filled"
        mock_trade.orderStatus.filled = 10.0
        mock_trade.orderStatus.avgFillPrice = 180.50

        mock_ib.trades.return_value = [mock_trade]
        adapter._ib = mock_ib

        status = await adapter.get_order_status("12345")
        assert status["status"] == "Filled"
        assert status["filled_qty"] == 10.0
        assert status["fill_price"] == 180.50

    @pytest.mark.asyncio
    async def test_get_order_status_not_found(self, adapter, mock_ib):
        """Test get order status for unknown order."""
        mock_ib.trades.return_value = []
        adapter._ib = mock_ib

        status = await adapter.get_order_status("99999")
        assert status["status"] == "unknown"
        assert status["filled_qty"] == 0

    @pytest.mark.asyncio
    async def test_get_positions(self, adapter, mock_ib):
        """Test get positions."""
        mock_position = MagicMock()
        mock_position.contract = MagicMock()
        mock_position.contract.symbol = "SPY   "
        mock_position.contract.lastTradeDateOrContractMonth = "20260616"
        mock_position.contract.right = "C"
        mock_position.contract.strike = 600.0
        mock_position.position = 5.0
        mock_position.avgCost = 350.0

        # Mock isinstance check
        with patch("shared.broker.ibkr_adapter.Option"):
            mock_position.contract.__class__.__name__ = "Option"
            mock_ib.positions.return_value = [mock_position]
            adapter._ib = mock_ib

            positions = await adapter.get_positions()
            assert len(positions) == 1
            assert positions[0]["quantity"] == 5

    @pytest.mark.asyncio
    async def test_get_quote(self, adapter, mock_ib):
        """Test get quote."""
        mock_ticker = MagicMock()
        mock_ticker.bid = 3.40
        mock_ticker.ask = 3.50
        mock_ticker.last = 3.45

        mock_ib.reqTickers.return_value = [mock_ticker]
        adapter._ib = mock_ib

        quote = await adapter.get_quote("SPY260616C00600000")
        assert quote["bid"] == 3.40
        assert quote["ask"] == 3.50
        assert quote["last"] == 3.45

    @pytest.mark.asyncio
    async def test_get_account(self, adapter, mock_ib):
        """Test get account summary."""
        mock_values = [
            MagicMock(tag="BuyingPower", value="25000.0"),
            MagicMock(tag="TotalCashValue", value="10000.0"),
            MagicMock(tag="NetLiquidation", value="50000.0"),
        ]
        mock_ib.accountSummary.return_value = mock_values
        adapter._ib = mock_ib

        account = await adapter.get_account()
        assert account["buying_power"] == 25000.0
        assert account["cash"] == 10000.0
        assert account["equity"] == 50000.0

    @pytest.mark.asyncio
    async def test_close_position(self, adapter, mock_ib):
        """Test close position."""
        mock_position = MagicMock()
        mock_position.contract = MagicMock()
        mock_position.contract.symbol = "SPY"
        mock_position.position = 5.0

        mock_ib.positions.return_value = [mock_position]
        mock_ib.placeOrder = MagicMock()
        adapter._ib = mock_ib

        # Mock contract conversion
        with patch.object(adapter, "_contract_to_occ", return_value="SPY"):
            result = await adapter.close_position("SPY")
            assert result is True
            mock_ib.placeOrder.assert_called_once()

    def test_format_option_symbol(self, adapter):
        """Test format_option_symbol for IBKR OCC format."""
        result = adapter.format_option_symbol("SPY", "2026-06-16", "C", 600.0)
        assert result == "SPY   260616C00600000"

        result = adapter.format_option_symbol("AAPL", "2026-04-18", "P", 190.5)
        assert result == "AAPL  260418P00190500"

        # Short ticker
        result = adapter.format_option_symbol("QQQ", "2026-05-15", "C", 450.0)
        assert result == "QQQ   260515C00450000"

    def test_parse_symbol_option(self, adapter):
        """Test parsing OCC option symbol to ib_insync Contract."""
        with patch("shared.broker.ibkr_adapter.Option") as MockOption:
            contract = adapter._parse_symbol("SPY   260616C00600000")
            MockOption.assert_called_once_with("SPY", "20260616", 600.0, "C", "SMART")

    def test_parse_symbol_stock(self, adapter):
        """Test parsing stock symbol to ib_insync Contract."""
        with patch("shared.broker.ibkr_adapter.Stock") as MockStock:
            contract = adapter._parse_symbol("AAPL")
            MockStock.assert_called_once_with("AAPL", "SMART", "USD")

    def test_contract_to_occ_option(self, adapter):
        """Test converting ib_insync Option back to OCC."""
        mock_option = MagicMock()
        mock_option.symbol = "SPY"
        mock_option.lastTradeDateOrContractMonth = "20260616"
        mock_option.right = "C"
        mock_option.strike = 600.0

        with patch("shared.broker.ibkr_adapter.Option"):
            mock_option.__class__.__name__ = "Option"
            with patch("isinstance", return_value=True):
                result = adapter._contract_to_occ(mock_option)
                # Expect SPY   260616C00600000
                assert result.startswith("SPY")
                assert "260616C00600000" in result

    def test_contract_to_occ_stock(self, adapter):
        """Test converting ib_insync Stock back to symbol."""
        mock_stock = MagicMock()
        mock_stock.symbol = "AAPL"

        with patch("shared.broker.ibkr_adapter.Stock"):
            mock_stock.__class__.__name__ = "Stock"
            with patch("isinstance", side_effect=lambda obj, cls: cls.__name__ == "Stock"):
                result = adapter._contract_to_occ(mock_stock)
                assert result == "AAPL"

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_failures(self, adapter, mock_ib):
        """Test circuit breaker opens after repeated failures."""
        mock_ib.isConnected.return_value = False
        mock_ib.connectAsync = AsyncMock(side_effect=Exception("Connection refused"))

        adapter._ib = mock_ib

        # Trigger 3 failures
        for _ in range(3):
            try:
                await adapter.place_limit_order("SPY260616C00600000", 1, "buy", 3.50)
            except BrokerAPIError:
                pass

        # Circuit should be OPEN now
        with pytest.raises(BrokerAPIError) as exc_info:
            await adapter.place_limit_order("SPY260616C00600000", 1, "buy", 3.50)
        assert "circuit breaker is OPEN" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_disconnect(self, adapter, mock_ib):
        """Test disconnecting from IB Gateway."""
        adapter._ib = mock_ib
        await adapter.disconnect()
        mock_ib.disconnect.assert_called_once()
        assert adapter._connected is False

    def test_on_disconnected_callback(self, adapter):
        """Test disconnection event callback."""
        adapter._connected = True
        adapter._on_disconnected()
        assert adapter._connected is False

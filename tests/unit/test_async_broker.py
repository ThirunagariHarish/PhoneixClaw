from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from shared.broker.alpaca_adapter import AlpacaBrokerAdapter


@pytest.fixture
def adapter():
    with patch("shared.broker.alpaca_adapter.TradingClient"):
        return AlpacaBrokerAdapter(api_key="test-key", secret_key="test-secret", paper=True)


class TestAlpacaBrokerAdapter:
    def test_format_option_symbol(self, adapter):
        symbol = adapter.format_option_symbol("SPX", "2026-02-20", "CALL", 6940.0)
        assert "SPX" in symbol
        assert "C" in symbol
        assert "260220" in symbol

    @pytest.mark.asyncio
    async def test_place_limit_order(self, adapter):
        fake_order = SimpleNamespace(id="order-123")
        adapter._client.submit_order = MagicMock(return_value=fake_order)
        order_id = await adapter.place_limit_order("SPX260220C06940000", 1, "BUY", 4.80)
        assert order_id == "order-123"

    @pytest.mark.asyncio
    async def test_get_account(self, adapter):
        fake_account = SimpleNamespace(
            buying_power="50000.00", cash="50000.00",
            equity="50000.00", portfolio_value="50000.00",
        )
        adapter._client.get_account = MagicMock(return_value=fake_account)
        account = await adapter.get_account()
        assert account["buying_power"] == 50000.0

    @pytest.mark.asyncio
    async def test_cancel_order(self, adapter):
        adapter._client.cancel_order_by_id = MagicMock(return_value=None)
        result = await adapter.cancel_order("order-456")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_order_status(self, adapter):
        from alpaca.trading.enums import OrderStatus
        fake_order = SimpleNamespace(
            status=OrderStatus.FILLED, filled_qty="1", filled_avg_price="4.90",
        )
        adapter._client.get_order_by_id = MagicMock(return_value=fake_order)
        status = await adapter.get_order_status("order-789")
        assert status["status"] == "filled"
        assert status["filled_qty"] == 1

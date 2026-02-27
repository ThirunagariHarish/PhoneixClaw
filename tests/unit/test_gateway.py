from unittest.mock import AsyncMock

import pytest

from services.trade_gateway.src.gateway import TradeGatewayService


class TestTradeGateway:
    @pytest.mark.asyncio
    async def test_auto_approve_sets_status(self):
        gw = TradeGatewayService.__new__(TradeGatewayService)
        gw.mode = "auto"
        gw.producer = AsyncMock()
        gw.producer.send = AsyncMock()

        trade = {
            "trade_id": "test-123",
            "action": "BUY",
            "ticker": "SPX",
            "user_id": "user-1",
        }
        await gw._handle_trade(trade, {})

        assert trade["status"] == "IN_PROGRESS"
        assert trade["approved_by"] == "auto-gateway"
        gw.producer.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_manual_mode_sets_pending(self):
        gw = TradeGatewayService.__new__(TradeGatewayService)
        gw.mode = "manual"
        gw.producer = AsyncMock()
        gw.producer.send = AsyncMock()

        trade = {
            "trade_id": "test-456",
            "action": "BUY",
            "ticker": "SPX",
            "user_id": "user-1",
        }
        await gw._handle_trade(trade, {})

        assert trade["status"] == "PENDING"
        gw.producer.send.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_approved_trade_has_timestamp(self):
        gw = TradeGatewayService.__new__(TradeGatewayService)
        gw.mode = "auto"
        gw.producer = AsyncMock()
        gw.producer.send = AsyncMock()

        trade = {"trade_id": "test-789", "action": "SELL", "ticker": "AAPL", "user_id": ""}
        await gw._handle_trade(trade, {})

        assert "approved_at" in trade

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trade_executor.src.fill_tracker import FillTracker

TRADE_UUID = "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
TRADE_UUID_2 = "b2c3d4e5-f6a7-8901-bcde-f12345678901"
USER_UUID = "00000000-0000-0000-0000-000000000001"
ACCOUNT_UUID = "00000000-0000-0000-0000-000000000002"


class TestFillTracker:
    def test_init(self):
        ft = FillTracker()
        assert ft._pending == []
        assert ft._running is False

    @pytest.mark.asyncio
    async def test_track_adds_to_pending(self):
        ft = FillTracker()
        broker = AsyncMock()
        trade = {"trade_id": TRADE_UUID, "action": "BUY", "ticker": "AAPL"}
        await ft.track("ORDER-1", trade, broker)
        assert len(ft._pending) == 1
        assert ft._pending[0]["order_id"] == "ORDER-1"

    @pytest.mark.asyncio
    async def test_poll_filled_order(self):
        ft = FillTracker()
        broker = AsyncMock()
        broker.get_order_status.return_value = {
            "status": "FILLED",
            "filled_qty": 5,
            "fill_price": 3.50,
        }
        trade = {
            "trade_id": TRADE_UUID,
            "action": "BUY",
            "ticker": "AAPL",
            "user_id": USER_UUID,
            "trading_account_id": ACCOUNT_UUID,
        }
        await ft.track("ORDER-1", trade, broker)

        with patch("services.trade_executor.src.fill_tracker.AsyncSessionLocal") as mock_session:
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.execute = AsyncMock()
            mock_ctx.commit = AsyncMock()
            mock_ctx.add = MagicMock()
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = None
            mock_ctx.execute.return_value = mock_result

            await ft._poll_cycle()

        assert len(ft._pending) == 0
        broker.get_order_status.assert_called_once_with("ORDER-1")

    @pytest.mark.asyncio
    async def test_poll_cancelled_order(self):
        ft = FillTracker()
        broker = AsyncMock()
        broker.get_order_status.return_value = {
            "status": "CANCELLED",
            "filled_qty": 0,
            "fill_price": 0,
        }
        trade = {"trade_id": TRADE_UUID_2, "action": "BUY", "ticker": "SPY"}
        await ft.track("ORDER-2", trade, broker)

        with patch("services.trade_executor.src.fill_tracker.AsyncSessionLocal") as mock_session:
            mock_ctx = AsyncMock()
            mock_session.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_session.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_ctx.execute = AsyncMock()
            mock_ctx.commit = AsyncMock()

            await ft._poll_cycle()

        assert len(ft._pending) == 0

    @pytest.mark.asyncio
    async def test_start_stop(self):
        ft = FillTracker()
        await ft.start()
        assert ft._running is True
        await ft.stop()
        assert ft._running is False

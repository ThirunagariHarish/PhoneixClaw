"""End-to-end integration tests for the trade executor flow.

Verifies: header merge, broker resolution, validation, and execution path.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.trade_executor.src.executor import TradeExecutorService


class TestExecutorHeaderMerge:
    """Verify Kafka headers are merged into trade for broker resolution."""

    @pytest.mark.asyncio
    async def test_headers_merge_user_id_and_trading_account_id(self):
        service = TradeExecutorService()
        service.producer = AsyncMock()

        broker = AsyncMock()
        broker.place_limit_order = AsyncMock(return_value="order-123")
        broker.format_option_symbol = MagicMock(return_value="SPY260224C00580000")
        broker.get_account = AsyncMock(return_value={
            "buying_power": 100000, "cash": 50000,
            "equity": 100000, "portfolio_value": 100000,
        })

        trade = {
            "trade_id": "test-header-merge",
            "ticker": "SPY",
            "action": "BUY",
            "strike": 580,
            "option_type": "CALL",
            "price": 2.50,
            "quantity": "1",
            "expiration": "2026-02-24",
            "source": "discord",
        }
        headers = {
            "user_id": b"user-abc-123",
            "trading_account_id": b"account-def-456",
        }

        with patch.object(service, "_resolve_broker", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = broker
            with patch.object(service, "_publish_result", new_callable=AsyncMock) as mock_publish:
                with patch.object(service, "_fill_tracker") as mock_ft:
                    mock_ft.track = AsyncMock()
                    await service._handle_trade(trade, headers)

                mock_resolve.assert_called_once()
                resolved_trade = mock_resolve.call_args[0][0]
                assert resolved_trade.get("user_id") == "user-abc-123"
                assert resolved_trade.get("trading_account_id") == "account-def-456"
                mock_publish.assert_called_once()
                assert mock_publish.call_args[0][1] == "EXECUTED"


class TestExecutorExecutionFlow:
    """Verify full execution path with mock broker."""

    @pytest.mark.asyncio
    async def test_trade_with_trading_account_id_executes(self):
        service = TradeExecutorService()
        service.producer = AsyncMock()

        broker = AsyncMock()
        broker.place_limit_order = AsyncMock(return_value="alpaca-order-xyz")
        broker.format_option_symbol = MagicMock(return_value="SPXW260224C06895000")
        broker.get_account = AsyncMock(return_value={
            "buying_power": 100000, "cash": 50000,
            "equity": 100000, "portfolio_value": 100000,
        })

        trade = {
            "trade_id": "test-exec-1",
            "user_id": "user-1",
            "trading_account_id": "account-1",
            "ticker": "SPX",
            "action": "BUY",
            "strike": 6895,
            "option_type": "CALL",
            "price": 2.60,
            "quantity": "1",
            "expiration": "2026-02-24",
            "source": "discord",
        }

        with patch.object(service, "_resolve_broker", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = broker
            with patch.object(service, "_publish_result", new_callable=AsyncMock) as mock_publish:
                with patch.object(service, "_fill_tracker") as mock_ft:
                    mock_ft.track = AsyncMock()
                    await service._handle_trade(trade, {})

                mock_publish.assert_called_once()
                call_args = mock_publish.call_args
                assert call_args[0][1] == "EXECUTED"
                assert trade.get("broker_order_id") == "alpaca-order-xyz"
                assert trade.get("broker_symbol") == "SPXW260224C06895000"

    @pytest.mark.asyncio
    async def test_dry_run_marks_executed_without_broker_call(self):
        service = TradeExecutorService()
        service._dry_run = True
        service.producer = AsyncMock()

        broker = AsyncMock()
        broker.place_limit_order = AsyncMock()
        broker.format_option_symbol = MagicMock(return_value="SPY260224C00580000")

        trade = {
            "trade_id": "test-dry-1",
            "user_id": "user-1",
            "trading_account_id": "account-1",
            "ticker": "SPY",
            "action": "BUY",
            "strike": 580,
            "option_type": "CALL",
            "price": 2.50,
            "quantity": "1",
            "expiration": "2026-02-24",
            "source": "discord",
        }

        with patch.object(service, "_resolve_broker", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = broker
            with patch.object(service, "_publish_result", new_callable=AsyncMock) as mock_publish:
                with patch.object(service, "_create_dry_run_position", new_callable=AsyncMock):
                    await service._handle_trade(trade, {})

                mock_publish.assert_called_once()
                assert mock_publish.call_args[0][1] == "EXECUTED"
                broker.place_limit_order.assert_not_called()
                assert trade.get("broker_order_id", "").startswith("DRY-")

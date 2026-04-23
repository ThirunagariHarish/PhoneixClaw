"""Unit tests for the backtest simulation engine."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from shared.backtest.engine import run_backtest


class TestRunBacktest:
    """Test run_backtest with synthetic messages."""

    def _msg(self, content: str, ts: datetime | None = None) -> dict:
        t = ts or datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        return {"content": content, "timestamp": t, "author": "test", "message_id": "1"}

    def test_empty_messages_returns_empty_trades(self):
        trades, summary = run_backtest([])
        assert trades == []
        assert summary["total_trades"] == 0
        assert summary["executed_trades"] == 0
        assert summary["total_pnl"] == 0

    def test_single_buy_no_sell_closes_at_expired(self):
        """BUY without matching SELL closes at 0 PnL (EXPIRED)."""
        msgs = [
            self._msg("BTO AAPL 190C 3/21 @ 2.50", datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
        ]
        trades, summary = run_backtest(msgs)
        assert summary["total_trades"] == 1
        assert summary["executed_trades"] == 0
        assert trades[0]["exit_reason"] == "EXPIRED"
        assert trades[0]["realized_pnl"] == 0.0
        assert trades[0]["ticker"] == "AAPL"
        assert trades[0]["strike"] == 190.0
        assert trades[0]["option_type"] == "CALL"

    def test_buy_then_sell_produces_executed_trade(self):
        """BUY followed by SELL produces executed trade with PnL (x100 options multiplier)."""
        msgs = [
            self._msg("BTO AAPL 190C 3/21 @ 2.50", datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            self._msg("STC AAPL 190C @ 3.00", datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
        ]
        trades, summary = run_backtest(msgs)
        assert summary["executed_trades"] == 1
        assert summary["total_trades"] == 1
        assert trades[0]["exit_reason"] == "MANUAL"
        assert trades[0]["realized_pnl"] == 50.0  # (3.00 - 2.50) * 100
        assert trades[0]["entry_price"] == 2.50
        assert trades[0]["exit_price"] == 3.00

    def test_buy_sell_matching_without_expiration_in_sell(self):
        """SELL message without expiration still matches BUY (position_key uses ticker+strike+type)."""
        msgs = [
            self._msg("Bought SPX 5000C at 4.80", datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            self._msg("Sold SPX 5000C at 6.00", datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone.utc)),
        ]
        trades, summary = run_backtest(msgs)
        assert summary["executed_trades"] == 1
        assert trades[0]["realized_pnl"] == pytest.approx(120.0)  # (6.00 - 4.80) * 100

    def test_multiple_buys_then_sells_fifo(self):
        """Multiple BUYs then SELLs close in FIFO order."""
        msgs = [
            self._msg("BTO SPY 500C 3/21 @ 2.00", datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            self._msg("BTO SPY 500C 3/21 @ 2.20", datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc)),
            self._msg("STC SPY 500C @ 2.50", datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
        ]
        trades, summary = run_backtest(msgs)
        # First SELL closes first BUY (2.00 entry) -> PnL = (2.50 - 2.00) * 100 = 50
        assert summary["executed_trades"] == 1
        assert trades[0]["entry_price"] == 2.0
        assert trades[0]["realized_pnl"] == 50.0
        # Second position closes at 0 PnL (EXPIRED)
        assert summary["total_trades"] == 2
        assert trades[1]["exit_reason"] == "EXPIRED"
        assert trades[1]["realized_pnl"] == 0.0

    def test_put_option_pnl_calculation(self):
        """PUT option premium: BUY at 3.00, SELL at 4.00.

        Engine applies take-profit at 30%: tp = 3.00 * 1.30 = 3.90.
        Since 4.00 >= 3.90, exit is capped at 3.90 (TAKE_PROFIT).
        PnL = (3.90 - 3.00) * 100 = 90.0
        """
        msgs = [
            self._msg("BTO AAPL 180P 3/21 @ 3.00", datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc)),
            self._msg("STC AAPL 180P @ 4.00", datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc)),
        ]
        trades, summary = run_backtest(msgs)
        assert summary["executed_trades"] == 1
        assert trades[0]["exit_reason"] == "TAKE_PROFIT"
        assert trades[0]["realized_pnl"] == pytest.approx(90.0)

    def test_ignores_non_trade_messages(self):
        """Messages that don't parse as trades are skipped."""
        msgs = [
            self._msg("Hey everyone, market looks bullish!"),
            self._msg("BTO AAPL 190C 3/21 @ 2.50"),
            self._msg("Great trade!"),
        ]
        trades, summary = run_backtest(msgs)
        assert summary["total_trades"] == 1
        assert trades[0]["ticker"] == "AAPL"

    def test_summary_has_required_fields(self):
        """Summary contains all expected metrics."""
        msgs = [
            self._msg("BTO AAPL 190C 3/21 @ 2.50"),
            self._msg("STC AAPL 190C @ 3.00"),
        ]
        _, summary = run_backtest(msgs)
        assert "total_trades" in summary
        assert "executed_trades" in summary
        assert "winning_trades" in summary
        assert "losing_trades" in summary
        assert "total_pnl" in summary
        assert "win_rate_pct" in summary
        assert "avg_win" in summary
        assert "avg_loss" in summary
        assert "max_drawdown" in summary
        assert "profit_factor" in summary

    def test_trade_dict_has_required_fields(self):
        """Each trade dict has fields needed for BacktestTrade."""
        msgs = [
            self._msg("BTO AAPL 190C 3/21 @ 2.50"),
            self._msg("STC AAPL 190C @ 3.00"),
        ]
        trades, _ = run_backtest(msgs)
        t = trades[0]
        assert "trade_id" in t
        assert "ticker" in t
        assert "strike" in t
        assert "option_type" in t
        assert "action" in t
        assert "quantity" in t
        assert "entry_price" in t
        assert "exit_price" in t
        assert "entry_ts" in t
        assert "exit_ts" in t
        assert "exit_reason" in t
        assert "realized_pnl" in t
        assert "raw_message" in t

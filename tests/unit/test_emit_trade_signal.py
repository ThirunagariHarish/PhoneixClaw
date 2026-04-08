"""Tests for agents/analyst/tools/emit_trade_signal.py"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from unittest.mock import patch


def test_emit_returns_empty_string_on_db_failure():
    """When DB raises, emit_trade_signal must return empty string, not a fake UUID."""
    # create_async_engine is imported at module level in emit_trade_signal so it
    # can be patched here via its module-level binding.
    with patch("agents.analyst.tools.emit_trade_signal.create_async_engine") as mock_engine:
        mock_engine.side_effect = Exception("DB connection failed")
        from agents.analyst.tools.emit_trade_signal import emit_trade_signal
        result = asyncio.run(emit_trade_signal(
            agent_id="00000000-0000-0000-0000-000000000001",
            ticker="SPY",
            direction="buy",
            entry_price=450.0,
            stop_loss=445.0,
            take_profit=460.0,
            confidence=80,
            reasoning="test",
            analyst_persona="aggressive_momentum",
            tool_signals_used={},
            db_url="postgresql+asyncpg://test:test@localhost/test",
        ))
        assert result == "", f"Expected empty string on failure, got: {result!r}"


def test_emit_returns_empty_string_when_no_db_url():
    """When DATABASE_URL is unset and no db_url provided, must return empty string."""
    import importlib
    import agents.analyst.tools.emit_trade_signal as _mod

    original = os.environ.pop("DATABASE_URL", None)
    try:
        result = asyncio.run(_mod.emit_trade_signal(
            agent_id="00000000-0000-0000-0000-000000000002",
            ticker="AAPL",
            direction="sell",
            entry_price=175.0,
            stop_loss=178.0,
            take_profit=165.0,
            confidence=55,
            reasoning="no db test",
            analyst_persona="conservative_swing",
            tool_signals_used={},
            db_url=None,
        ))
        assert result == "", f"Expected empty string when no DB URL, got: {result!r}"
    finally:
        if original is not None:
            os.environ["DATABASE_URL"] = original

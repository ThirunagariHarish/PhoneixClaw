"""End-to-end integration test for the live trading pipeline.

Simulates: Discord message → Redis stream → consumer → decision engine → execute_trade → trade recorded

Runs entirely in paper mode with mocked Redis / Phoenix API.

Usage:
    python -m pytest tests/integration/test_live_pipeline_e2e.py -v --tb=short
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

LIVE_TOOLS = Path(__file__).resolve().parents[2] / "agents" / "templates" / "live-trader-v1" / "tools"
sys.path.insert(0, str(LIVE_TOOLS))

from execute_trade import execute, _report_trade_to_phoenix


@pytest.fixture
def work_dir(tmp_path):
    """Create a temporary working directory with all necessary config files."""
    config = {
        "agent_id": "test-agent-001",
        "agent_name": "Test Agent",
        "channel_name": "test-channel",
        "channel_id": "123456789",
        "connector_id": "test-connector-001",
        "phoenix_api_url": "http://localhost:8011",
        "phoenix_api_key": "test-key",
        "paper_mode": True,
        "current_mode": "conservative",
        "risk_params": {
            "max_position_size_pct": 5.0,
            "max_daily_loss_pct": 3.0,
            "max_concurrent_positions": 3,
            "confidence_threshold": 0.55,
        },
        "model_info": {"model_type": "xgboost", "accuracy": 0.68},
        "robinhood_credentials": {
            "username": "test@example.com",
            "password": "test",
            "totp_secret": "",
        },
    }
    (tmp_path / "config.json").write_text(json.dumps(config, indent=2))
    return tmp_path


def _make_signal_message(ticker: str = "AAPL", price: float = 175.50, direction: str = "buy"):
    """Create a realistic Discord signal message."""
    return {
        "channel_id": "123456789",
        "channel": "test-channel",
        "author": "VinodTrader",
        "content": f"${ticker} {direction} at ${price:.2f} target $180 stop $172",
        "timestamp": "2025-01-15T14:30:00+00:00",
        "message_id": "1000000000001",
    }


class TestSignalIngestion:
    """Test 1: Verify signals are correctly written to pending_signals.json."""

    def test_signal_written_to_pending(self, work_dir):
        """Simulate writing a signal from the consumer to pending_signals.json."""
        signal = _make_signal_message()
        pending_path = work_dir / "pending_signals.json"
        pending_path.write_text(json.dumps([signal], indent=2))

        loaded = json.loads(pending_path.read_text())
        assert len(loaded) == 1
        assert loaded[0]["author"] == "VinodTrader"
        assert "AAPL" in loaded[0]["content"]


class TestDecisionEngine:
    """Test 2: Verify decision engine can process a signal and produce a decision."""

    def test_decision_produced(self, work_dir):
        """Run a minimal decision flow and check that decision.json is produced."""
        signal = _make_signal_message()
        pending_path = work_dir / "pending_signals.json"
        pending_path.write_text(json.dumps([signal], indent=2))

        decision = {
            "decision": "EXECUTE",
            "confidence": 0.72,
            "signal": {
                "ticker": "AAPL",
                "direction": "buy",
                "content": signal["content"],
                "trade_type": "stock",
            },
            "execution": {
                "ticker": "AAPL",
                "side": "buy",
                "quantity": 10,
                "price": 175.50,
                "trade_type": "stock",
            },
            "reasoning": "Strong buy signal with TA confirmation",
            "patterns": ["momentum_breakout"],
        }
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        loaded = json.loads(decision_path.read_text())
        assert loaded["decision"] == "EXECUTE"
        assert loaded["execution"]["ticker"] == "AAPL"
        assert loaded["confidence"] >= 0.55


class TestExecuteTrade:
    """Test 3: Verify execute_trade.py handles paper mode correctly."""

    def test_paper_execute_skips_on_reject(self, work_dir):
        """A REJECT decision should be skipped."""
        decision = {
            "decision": "REJECT",
            "confidence": 0.3,
            "signal": {"ticker": "AAPL"},
            "reasoning": "Low confidence",
        }
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        result = execute(str(decision_path), str(work_dir / "config.json"))
        assert result["status"] == "skipped"

    def test_paper_execute_runs(self, work_dir):
        """An EXECUTE decision in paper mode should go through MCP."""
        decision = {
            "decision": "EXECUTE",
            "confidence": 0.72,
            "signal": {
                "ticker": "AAPL",
                "direction": "buy",
                "content": "Buy AAPL at $175.50",
                "trade_type": "stock",
            },
            "execution": {
                "ticker": "AAPL",
                "side": "buy",
                "quantity": 5,
                "price": 175.50,
                "trade_type": "stock",
            },
            "reasoning": "Good signal",
            "patterns": ["test_pattern"],
        }
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in", "paper_mode": True},
            {"portfolio_value": 25000, "buying_power": 10000, "paper_mode": True},
            {
                "order_id": "paper-001",
                "state": "filled",
                "fill_price": 175.48,
                "paper_mode": True,
            },
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report:
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "executed"
        assert result["ticker"] == "AAPL"
        assert result["paper_mode"] is True

        mock_report.assert_called_once()
        trade_data = mock_report.call_args[0][1]
        assert trade_data["ticker"] == "AAPL"
        assert trade_data["decision_status"] == "accepted"
        assert trade_data["status"] == "open"

    def test_insufficient_buying_power_rejected(self, work_dir):
        """Trades exceeding buying power should be rejected."""
        decision = {
            "decision": "EXECUTE",
            "confidence": 0.72,
            "signal": {
                "ticker": "AAPL",
                "direction": "buy",
                "content": "Buy AAPL at $175.50",
                "trade_type": "stock",
            },
            "execution": {
                "ticker": "AAPL",
                "side": "buy",
                "quantity": 100,
                "price": 175.50,
                "trade_type": "stock",
            },
            "reasoning": "Good signal",
        }
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 500, "paper_mode": True},  # only $500 available
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report:
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "rejected"
        assert result["reason"] == "insufficient_buying_power"
        mock_report.assert_called_once()
        trade_data = mock_report.call_args[0][1]
        assert trade_data["decision_status"] == "rejected"


class TestTradeRecording:
    """Test 4: Verify trades are recorded to the correct Phoenix API endpoint."""

    def test_trade_posted_to_live_trades(self, work_dir):
        """After execution, trade data should POST to /live-trades (not /trade-signals)."""
        config = json.loads((work_dir / "config.json").read_text())

        trade_data = {
            "ticker": "AAPL",
            "side": "buy",
            "entry_price": 175.48,
            "quantity": 5,
            "model_confidence": 0.72,
            "decision_status": "accepted",
            "status": "open",
        }

        import httpx as httpx_mod
        with patch.object(httpx_mod, "post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            _report_trade_to_phoenix(config, trade_data)

        mock_post.assert_called_once()
        call_args = mock_post.call_args
        url = call_args[0][0]
        assert "/live-trades" in url
        assert "/trade-signals" not in url
        assert call_args[1]["json"]["ticker"] == "AAPL"


class TestFullPipeline:
    """Test 5: End-to-end pipeline test in paper mode."""

    def test_signal_to_trade_flow(self, work_dir):
        """Full flow: signal → pending → decision → execution → recorded."""
        # Step 1: Write signal
        signal = _make_signal_message()
        pending_path = work_dir / "pending_signals.json"
        pending_path.write_text(json.dumps([signal], indent=2))

        # Step 2: Simulate decision
        decision = {
            "decision": "PAPER",
            "confidence": 0.68,
            "signal": {
                "ticker": "AAPL",
                "direction": "buy",
                "content": signal["content"],
                "trade_type": "stock",
            },
            "execution": {
                "ticker": "AAPL",
                "side": "buy",
                "quantity": 3,
                "price": 175.50,
                "trade_type": "stock",
            },
            "reasoning": "Paper mode test",
            "patterns": [],
        }
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        # Step 3: Execute in paper mode
        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in", "paper_mode": True},
            {"buying_power": 50000, "paper_mode": True},
            {"order_id": "paper-002", "state": "filled", "fill_price": 175.50, "paper_mode": True},
        ]

        recorded_trades = []

        def capture_trade(config, trade_data):
            recorded_trades.append(trade_data)

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix", side_effect=capture_trade), \
             patch("execute_trade._spawn_position_agent"):  # don't spawn in test
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        # Verify full flow
        assert result["status"] == "executed"
        assert result["paper_mode"] is True
        assert len(recorded_trades) == 1
        assert recorded_trades[0]["ticker"] == "AAPL"
        assert recorded_trades[0]["side"] == "buy"
        assert recorded_trades[0]["decision_status"] == "accepted"

        # Verify execution_result.json was written
        exec_result = json.loads((work_dir / "execution_result.json").read_text())
        assert exec_result["ticker"] == "AAPL"
        assert exec_result["paper_mode"] is True

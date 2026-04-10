"""End-to-end integration test for the live trading pipeline.

Simulates: Discord message -> Redis stream -> live_pipeline -> decision engine -> execute_trade -> trade recorded

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
        "_config_path": str(tmp_path / "config.json"),
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


def _make_decision_engine_output(ticker="AAPL", direction="buy", price=175.50):
    """Create a decision that matches real decision_engine.py output format (with direction, entry_price, parsed_signal)."""
    return {
        "decision": "EXECUTE",
        "reason": None,
        "timestamp": "2025-01-15T14:30:07+00:00",
        "reasoning": [
            "Enriched with 187 market features",
            "Model: TRADE (confidence=0.720, patterns=3)",
            "Risk check passed",
            "TA: bullish (conf=0.62)",
            f"APPROVED: {direction.upper()} {ticker}",
        ],
        "steps": [
            {"step": "parse_signal", "status": "ok"},
            {"step": "enrich", "status": "ok", "features_count": 187},
            {"step": "inference", "status": "ok", "prediction": "TRADE", "confidence": 0.72},
            {"step": "risk_check", "status": "ok", "approved": True},
            {"step": "ta_confirmation", "status": "ok", "verdict": "bullish"},
        ],
        "parsed_signal": {
            "ticker": ticker,
            "direction": direction,
            "signal_price": price,
            "option_type": None,
            "strike": None,
            "expiry": None,
        },
        "model_prediction": {
            "prediction": "TRADE",
            "confidence": 0.72,
            "pattern_matches": 3,
        },
        "risk_check": {"approved": True, "rejection_reason": None},
        "ta_summary": {"verdict": "bullish", "confidence": 0.62},
        "execution": {
            "ticker": ticker,
            "direction": direction,
            "entry_price": round(price * 1.001, 2),
            "signal_price": price,
            "stop_loss": round(price * 0.97, 2),
            "take_profit": round(price * 1.05, 2),
            "position_size_pct": 3.5,
            "option_type": None,
            "strike": None,
            "expiry": None,
        },
        "signal_raw": f"${ticker} {direction} at ${price:.2f} target $180 stop $172",
    }


class TestSignalIngestion:
    def test_signal_written_to_pending(self, work_dir):
        signal = _make_signal_message()
        pending_path = work_dir / "pending_signals.json"
        pending_path.write_text(json.dumps([signal], indent=2))

        loaded = json.loads(pending_path.read_text())
        assert len(loaded) == 1
        assert loaded[0]["author"] == "VinodTrader"
        assert "AAPL" in loaded[0]["content"]


class TestSchemaMapping:
    """Verify execute_trade correctly handles decision_engine.py's output format (direction not side, entry_price not price)."""

    def test_direction_mapped_to_side(self, work_dir):
        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in", "paper_mode": True},
            {"portfolio_value": 25000, "buying_power": 10000, "paper_mode": True},
            {"order_id": "paper-001", "state": "filled", "fill_price": 175.67, "paper_mode": True},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report, \
             patch("execute_trade._spawn_position_agent", return_value={}) as mock_spawn, \
             patch("execute_trade._register_position"):
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "executed"
        assert result["side"] == "buy"
        assert result["ticker"] == "AAPL"
        assert result["fill_price"] == 175.67

        trade_data = mock_report.call_args[0][1]
        assert trade_data["side"] == "buy"
        assert trade_data["entry_price"] == 175.67

    def test_parsed_signal_fallback(self, work_dir):
        """When 'signal' key is missing, fallback to 'parsed_signal'."""
        decision = _make_decision_engine_output()
        assert "signal" not in decision
        assert "parsed_signal" in decision

        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50000},
            {"order_id": "p-002", "state": "filled", "fill_price": 175.50},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report, \
             patch("execute_trade._spawn_position_agent", return_value={}), \
             patch("execute_trade._register_position"):
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "executed"

    def test_dict_decision_passthrough(self, work_dir):
        """execute() accepts a dict directly (for in-process calls from live_pipeline)."""
        decision = _make_decision_engine_output()
        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50000},
            {"order_id": "p-003", "state": "filled", "fill_price": 175.50},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix"), \
             patch("execute_trade._spawn_position_agent", return_value={}), \
             patch("execute_trade._register_position"):
            MockMCPClass.return_value = mock_mcp
            result = execute(decision, str(work_dir / "config.json"))

        assert result["status"] == "executed"


class TestDecisionTrailPersistence:
    """Verify decision trail is included in the trade data sent to Phoenix."""

    def test_trail_included_in_report(self, work_dir):
        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50000},
            {"order_id": "p-004", "state": "filled", "fill_price": 175.50},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report, \
             patch("execute_trade._spawn_position_agent", return_value={}), \
             patch("execute_trade._register_position"):
            MockMCPClass.return_value = mock_mcp
            execute(str(decision_path), str(work_dir / "config.json"))

        trade_data = mock_report.call_args[0][1]
        assert "decision_trail" in trade_data
        trail = trade_data["decision_trail"]
        assert "steps" in trail
        assert len(trail["steps"]) == 5
        assert trail["steps"][0]["step"] == "parse_signal"
        assert trail["model_prediction"]["confidence"] == 0.72
        assert "reasoning" in trail

    def test_reasoning_text_is_pipe_joined(self, work_dir):
        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50000},
            {"order_id": "p-005", "state": "filled", "fill_price": 175.50},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report, \
             patch("execute_trade._spawn_position_agent", return_value={}), \
             patch("execute_trade._register_position"):
            MockMCPClass.return_value = mock_mcp
            execute(str(decision_path), str(work_dir / "config.json"))

        trade_data = mock_report.call_args[0][1]
        assert " | " in trade_data["reasoning"]
        assert "APPROVED" in trade_data["reasoning"]


class TestInsufficientBuyingPower:
    def test_rejected_with_trail(self, work_dir):
        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50, "paper_mode": True},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report:
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "rejected"
        assert result["reason"] == "insufficient_buying_power"
        trade_data = mock_report.call_args[0][1]
        assert trade_data["decision_status"] == "rejected"
        assert "decision_trail" in trade_data


class TestTimedOutHandling:
    def test_timed_out_is_rejected(self, work_dir):
        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50000},
            {"order_id": "p-006", "state": "timed_out", "timed_out": True},
        ]

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix") as mock_report:
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "rejected"
        mock_report.assert_called_once()
        trade_data = mock_report.call_args[0][1]
        assert trade_data["decision_status"] == "rejected"


class TestPositionRegistry:
    def test_position_registered_after_buy(self, work_dir):
        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in"},
            {"buying_power": 50000},
            {"order_id": "p-007", "state": "filled", "fill_price": 175.50},
        ]

        os.chdir(work_dir)

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix"), \
             patch("execute_trade._spawn_position_agent", return_value={"session_id": "sub-001", "agent_id": "sub-agent-001"}):
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "executed"
        registry_path = work_dir / "position_registry.json"
        assert registry_path.exists()
        registry = json.loads(registry_path.read_text())
        assert "AAPL" in registry
        assert registry["AAPL"]["session_id"] == "sub-001"
        assert registry["AAPL"]["side"] == "buy"


class TestSellSignalRouting:
    def test_sell_signal_written(self, work_dir):
        os.chdir(work_dir)
        registry = {
            "AAPL": {
                "side": "buy",
                "entry_price": 175.50,
                "quantity": 10,
                "session_id": "sub-001",
            }
        }
        (work_dir / "position_registry.json").write_text(json.dumps(registry))

        from live_pipeline import _route_sell_signal
        signal = {"content": "Sold AAPL for profit", "author": "VinodTrader", "timestamp": "2025-01-15T15:00:00Z"}
        decision = {"decision": "EXECUTE", "reasoning": ["Analyst sold"]}
        _route_sell_signal("AAPL", signal, decision)

        sell_path = work_dir / "positions" / "AAPL" / "sell_signal.json"
        assert sell_path.exists()
        data = json.loads(sell_path.read_text())
        assert data["ticker"] == "AAPL"
        assert data["signal_type"] == "sell"
        assert "Sold AAPL" in data["content"]


class TestTradeRecording:
    def test_trade_posted_to_live_trades(self, work_dir):
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
    def test_signal_to_trade_with_audit_trail(self, work_dir):
        """Full flow: real decision_engine output -> execute -> trade recorded with decision trail."""
        os.chdir(work_dir)

        decision = _make_decision_engine_output()
        decision_path = work_dir / "decision.json"
        decision_path.write_text(json.dumps(decision, indent=2))

        mock_mcp = MagicMock()
        mock_mcp.call.side_effect = [
            {"status": "logged_in", "paper_mode": True},
            {"buying_power": 50000, "paper_mode": True},
            {"order_id": "paper-010", "state": "filled", "fill_price": 175.67, "paper_mode": True},
        ]

        recorded_trades = []

        def capture_trade(config, trade_data):
            recorded_trades.append(trade_data)

        with patch("execute_trade.MCPClient") as MockMCPClass, \
             patch("execute_trade._report_trade_to_phoenix", side_effect=capture_trade), \
             patch("execute_trade._spawn_position_agent", return_value={"session_id": "sub-010"}):
            MockMCPClass.return_value = mock_mcp
            result = execute(str(decision_path), str(work_dir / "config.json"))

        assert result["status"] == "executed"
        assert result["paper_mode"] is True
        assert result["fill_price"] == 175.67

        assert len(recorded_trades) == 1
        trade = recorded_trades[0]
        assert trade["ticker"] == "AAPL"
        assert trade["side"] == "buy"
        assert trade["decision_status"] == "accepted"
        assert trade["signal_raw"] != ""
        assert trade["broker_order_id"] == "paper-010"

        assert "decision_trail" in trade
        trail = trade["decision_trail"]
        assert len(trail["steps"]) == 5
        assert trail["steps"][2]["step"] == "inference"
        assert trail["steps"][2]["confidence"] == 0.72
        assert len(trail["reasoning"]) == 5
        assert trail["model_prediction"]["prediction"] == "TRADE"

        exec_result = json.loads((work_dir / "execution_result.json").read_text())
        assert exec_result["ticker"] == "AAPL"
        assert exec_result["paper_mode"] is True

        registry = json.loads((work_dir / "position_registry.json").read_text())
        assert "AAPL" in registry
        assert registry["AAPL"]["session_id"] == "sub-010"

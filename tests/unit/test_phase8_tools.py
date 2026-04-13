"""Tests for Phase 8 agent tools: execute_trade, add_to_watchlist, predict.

These tools communicate with broker-gateway and inference-service via HTTP.
Tests mock httpx calls to verify correct request construction and response handling.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config(tmp_path):
    config = {
        "agent_id": "test-agent-uuid",
        "phoenix_api_url": "http://localhost:8011",
        "phoenix_api_key": "test-key",
        "broker_gateway_url": "http://localhost:8040",
        "inference_service_url": "http://localhost:8045",
        "paper_mode": False,
        "risk_params": {"max_position_size_pct": 5.0},
    }
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps(config))
    return str(cfg_path), config


@pytest.fixture()
def tmp_decision(tmp_path):
    decision = {
        "decision": "EXECUTE",
        "execution": {
            "ticker": "AAPL",
            "direction": "buy",
            "entry_price": 190.0,
            "quantity": 10,
        },
        "parsed_signal": {
            "ticker": "AAPL",
            "direction": "buy",
            "signal_price": 190.0,
        },
        "reasoning": ["Model says TRADE", "Risk check passed"],
        "model_prediction": {"prediction": "TRADE", "confidence": 0.85},
        "steps": [],
    }
    dec_path = tmp_path / "decision.json"
    dec_path.write_text(json.dumps(decision))
    return str(dec_path), decision


# ---------------------------------------------------------------------------
# predict.py tests
# ---------------------------------------------------------------------------

class TestPredict:
    def _import_predict(self):
        import importlib
        import sys
        tools_dir = str(Path(__file__).resolve().parents[2] / "agents" / "templates" / "live-trader-v1" / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import predict
        importlib.reload(predict)
        return predict

    def test_predict_success(self):
        predict_mod = self._import_predict()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"prediction": "TRADE", "confidence": 0.85, "pattern_matches": 3}

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = predict_mod.predict(
                ticker="AAPL",
                agent_id="test-uuid",
                signal_features={"direction": "BUY"},
                inference_url="http://localhost:8045",
            )
        assert result["prediction"] == "TRADE"
        assert result["confidence"] == 0.85
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args
        assert "/predict" in call_kwargs.args[0] or "/predict" in str(call_kwargs)

    def test_predict_fallback_on_connect_error(self):
        predict_mod = self._import_predict()
        import httpx
        with patch("httpx.post", side_effect=httpx.ConnectError("connection refused")):
            result = predict_mod.predict(
                ticker="AAPL",
                agent_id="test-uuid",
                signal_features={"direction": "BUY"},
                inference_url="http://localhost:8045",
            )
        assert result["prediction"] == "SKIP"
        assert result["confidence"] == 0.0
        assert "unavailable" in result["reasoning"]

    def test_predict_fallback_on_timeout(self):
        predict_mod = self._import_predict()
        import httpx
        with patch("httpx.post", side_effect=httpx.TimeoutException("timed out")):
            result = predict_mod.predict(
                ticker="AAPL",
                agent_id="test-uuid",
                signal_features={},
                inference_url="http://localhost:8045",
            )
        assert result["prediction"] == "SKIP"
        assert "timeout" in result["reasoning"]

    def test_predict_fallback_on_http_error(self):
        predict_mod = self._import_predict()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        with patch("httpx.post", return_value=mock_resp):
            result = predict_mod.predict(
                ticker="AAPL",
                agent_id="test-uuid",
                signal_features={},
                inference_url="http://localhost:8045",
            )
        assert result["prediction"] == "SKIP"
        assert "500" in result["reasoning"]


# ---------------------------------------------------------------------------
# add_to_watchlist.py tests
# ---------------------------------------------------------------------------

class TestAddToWatchlist:
    def _import_module(self):
        import importlib
        import sys
        tools_dir = str(Path(__file__).resolve().parents[2] / "agents" / "templates" / "live-trader-v1" / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import add_to_watchlist
        importlib.reload(add_to_watchlist)
        return add_to_watchlist

    def test_add_to_watchlist_success(self):
        mod = self._import_module()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"status": "added", "symbols": ["PLTR"]}

        with patch("httpx.post", return_value=mock_resp) as mock_post:
            result = mod.add_to_watchlist("PLTR", "Phoenix Paper", "http://localhost:8040")
        assert result["status"] == "added"
        mock_post.assert_called_once()
        call_args = mock_post.call_args
        assert "/watchlist" in call_args.args[0]

    def test_add_to_watchlist_connect_error(self):
        mod = self._import_module()
        import httpx
        with patch("httpx.post", side_effect=httpx.ConnectError("refused")):
            result = mod.add_to_watchlist("PLTR", "Phoenix Paper", "http://localhost:8040")
        assert result["status"] == "error"
        assert "unreachable" in result["error"]

    def test_add_to_watchlist_http_error(self):
        mod = self._import_module()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "server error"
        with patch("httpx.post", return_value=mock_resp):
            result = mod.add_to_watchlist("PLTR", "Phoenix Paper", "http://localhost:8040")
        assert result["status"] == "error"


# ---------------------------------------------------------------------------
# execute_trade.py tests
# ---------------------------------------------------------------------------

class TestExecuteTrade:
    def _import_module(self):
        import importlib
        import sys
        tools_dir = str(Path(__file__).resolve().parents[2] / "agents" / "templates" / "live-trader-v1" / "tools")
        if tools_dir not in sys.path:
            sys.path.insert(0, tools_dir)
        import execute_trade
        importlib.reload(execute_trade)
        return execute_trade

    @pytest.fixture(autouse=True)
    def _disable_rth_gate(self, monkeypatch):
        monkeypatch.setenv("PHOENIX_BLOCK_EXECUTE_OUTSIDE_RTH", "false")

    def test_execute_stock_order_success(self, tmp_config, tmp_decision, tmp_path):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision_path, _ = tmp_decision

        mock_order_resp = MagicMock()
        mock_order_resp.status_code = 200
        mock_order_resp.json.return_value = {
            "order_id": "ord-123",
            "state": "filled",
            "fill_price": 190.50,
        }
        mock_phoenix_resp = MagicMock()
        mock_phoenix_resp.status_code = 200

        with patch("httpx.request", return_value=mock_order_resp):
            with patch("httpx.post", return_value=mock_phoenix_resp):
                result = mod.execute(decision_path, config_path)

        assert result["status"] == "executed"
        assert result["ticker"] == "AAPL"
        assert result["order_id"] == "ord-123"
        assert result["fill_price"] == 190.50

    def test_execute_skips_non_execute_decision(self, tmp_config, tmp_path):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision = {"decision": "REJECT", "reason": "model_skip"}
        dec_path = tmp_path / "reject.json"
        dec_path.write_text(json.dumps(decision))

        result = mod.execute(str(dec_path), config_path)
        assert result["status"] == "skipped"
        assert result["reason"] == "REJECT"

    def test_execute_no_ticker_error(self, tmp_config, tmp_path):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision = {"decision": "EXECUTE", "execution": {}, "parsed_signal": {}}
        dec_path = tmp_path / "noticker.json"
        dec_path.write_text(json.dumps(decision))

        result = mod.execute(str(dec_path), config_path)
        assert result["status"] == "error"
        assert result["reason"] == "no_ticker"

    def test_execute_broker_unreachable(self, tmp_config, tmp_decision):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision_path, _ = tmp_decision

        import httpx
        with patch("httpx.request", side_effect=httpx.ConnectError("refused")):
            result = mod.execute(decision_path, config_path)

        assert result["status"] == "error"
        assert result["reason"] == "broker_gateway_unreachable"

    def test_execute_broker_http_error(self, tmp_config, tmp_decision):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision_path, _ = tmp_decision

        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"
        mock_phoenix_resp = MagicMock()
        mock_phoenix_resp.status_code = 200

        with patch("httpx.request", return_value=mock_resp):
            with patch("httpx.post", return_value=mock_phoenix_resp):
                result = mod.execute(decision_path, config_path)

        assert result["status"] == "error"
        assert "broker_error_500" in result["reason"]

    def test_execute_option_order(self, tmp_config, tmp_path):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision = {
            "decision": "EXECUTE",
            "execution": {
                "ticker": "AAPL",
                "direction": "buy",
                "entry_price": 3.50,
                "quantity": 5,
                "strike": 190.0,
                "expiry": "2026-04-18",
                "option_type": "call",
            },
            "parsed_signal": {"ticker": "AAPL", "direction": "buy", "trade_type": "option"},
            "reasoning": [],
            "steps": [],
        }
        dec_path = tmp_path / "option_decision.json"
        dec_path.write_text(json.dumps(decision))

        mock_order_resp = MagicMock()
        mock_order_resp.status_code = 200
        mock_order_resp.json.return_value = {"order_id": "opt-456", "state": "filled", "fill_price": 3.60}
        mock_phoenix_resp = MagicMock()
        mock_phoenix_resp.status_code = 200

        with patch("httpx.request", return_value=mock_order_resp) as mock_req:
            with patch("httpx.post", return_value=mock_phoenix_resp):
                result = mod.execute(str(dec_path), config_path)

        assert result["status"] == "executed"
        call_args = mock_req.call_args
        assert "/orders/option" in call_args.args[1] or "/orders/option" in str(call_args)

    def test_dedup_signal(self, tmp_config, tmp_decision, tmp_path):
        mod = self._import_module()
        config_path, _ = tmp_config
        decision_path, _ = tmp_decision

        decision = json.loads(Path(decision_path).read_text())
        decision["signal_id"] = "sig-dedup-test"
        dec2 = tmp_path / "decision2.json"
        dec2.write_text(json.dumps(decision))

        executed_signals = tmp_path / "executed_signals.json"
        executed_signals.write_text(json.dumps(["sig-dedup-test"]))

        import os
        orig_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            result = mod.execute(str(dec2), config_path)
        finally:
            os.chdir(orig_cwd)

        assert result["status"] == "skipped"
        assert result["reason"] == "duplicate_signal"

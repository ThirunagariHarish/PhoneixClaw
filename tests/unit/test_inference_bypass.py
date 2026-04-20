"""Tests for the ML inference test-channel bypass.

When a signal arrives from a channel listed in $BYPASS_ML_CHANNELS
(default: text-trades), `predict()` must short-circuit to a TRADE verdict
without attempting to load any model files.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

LIVE_TRADER_TOOLS = Path(__file__).resolve().parents[2] / "agents" / "templates" / "live-trader-v1" / "tools"
sys.path.insert(0, str(LIVE_TRADER_TOOLS))


@pytest.fixture
def features_file(tmp_path: Path):
    def _make(channel: str, extra: dict | None = None) -> str:
        data = {"ticker": "AAPL", "channel": channel}
        if extra:
            data.update(extra)
        path = tmp_path / "features.json"
        path.write_text(json.dumps(data))
        return str(path)
    return _make


def test_bypass_triggers_on_text_trades_channel(features_file, tmp_path, monkeypatch):
    import inference

    monkeypatch.delenv("BYPASS_ML_CHANNELS", raising=False)
    path = features_file("text-trades")

    result = inference.predict(path, models_dir=str(tmp_path / "nonexistent_models"))

    assert result["prediction"] == "TRADE"
    assert result["bypass"] is True
    assert result["model"] == "bypass:test_channel"
    assert "text-trades" in result["bypass_reason"]


def test_bypass_case_insensitive(features_file, tmp_path, monkeypatch):
    import inference

    monkeypatch.delenv("BYPASS_ML_CHANNELS", raising=False)
    path = features_file("TEXT-TRADES")

    result = inference.predict(path, models_dir=str(tmp_path / "nonexistent_models"))
    assert result["bypass"] is True


def test_bypass_env_var_override(features_file, tmp_path, monkeypatch):
    import inference

    monkeypatch.setenv("BYPASS_ML_CHANNELS", "qa-sandbox, smoke-tests")
    path = features_file("smoke-tests")

    result = inference.predict(path, models_dir=str(tmp_path / "nonexistent_models"))
    assert result["bypass"] is True


def test_no_bypass_for_other_channels(features_file, tmp_path, monkeypatch):
    """When channel is not in the bypass list, predict must try to load models
    (and fail noisily here since no models exist — proving it did NOT short-circuit)."""
    import inference

    monkeypatch.delenv("BYPASS_ML_CHANNELS", raising=False)
    path = features_file("general")

    with pytest.raises((FileNotFoundError, OSError)):
        inference.predict(path, models_dir=str(tmp_path / "nonexistent_models"))


def test_no_bypass_when_channel_missing(features_file, tmp_path, monkeypatch):
    import inference

    monkeypatch.delenv("BYPASS_ML_CHANNELS", raising=False)
    path = features_file("")

    with pytest.raises((FileNotFoundError, OSError)):
        inference.predict(path, models_dir=str(tmp_path / "nonexistent_models"))


def test_signal_parser_propagates_channel():
    """parse_signal_compat must preserve the `channel` key so inference can see it."""
    from shared.utils.signal_parser import parse_signal_compat

    raw = {
        "content": "BTO $AAPL 185c 4/18 @ 3.50",
        "author": "vinod",
        "channel": "text-trades",
        "message_id": "abc123",
    }
    parsed = parse_signal_compat(raw)
    assert parsed["channel"] == "text-trades"


@pytest.mark.asyncio
async def test_pipeline_routes_bypass_to_watchlist(tmp_path, monkeypatch):
    """End-to-end: a text-trades signal flows through process_signal and
    comes out as decision=WATCHLIST (not EXECUTE), even when models exist."""
    import live_pipeline

    monkeypatch.delenv("BYPASS_ML_CHANNELS", raising=False)

    models_dir = tmp_path / "models"
    models_dir.mkdir()
    (models_dir / "dummy_model.pkl").write_bytes(b"\x00")

    monkeypatch.setattr(
        live_pipeline, "_log_to_phoenix", lambda *args, **kwargs: None, raising=True,
    )

    import market_session_gate
    monkeypatch.setattr(
        market_session_gate, "outside_rth_watchlist_payload",
        lambda *args, **kwargs: None, raising=True,
    )

    import enrich_single
    monkeypatch.setattr(
        enrich_single, "enrich_signal", lambda sig: {**sig, "last_close": 185.0}, raising=True,
    )

    import risk_check
    monkeypatch.setattr(
        risk_check, "check_risk",
        lambda *args, **kwargs: {"approved": True, "position_size": 1},
        raising=True,
    )

    watchlist_calls: list[tuple[str, str, str]] = []
    import add_to_watchlist as wl_module
    monkeypatch.setattr(
        wl_module, "add_to_watchlist",
        lambda ticker, watchlist_name, broker_url: (
            watchlist_calls.append((ticker, watchlist_name, broker_url))
            or {"status": "added", "ticker": ticker, "watchlist_name": watchlist_name}
        ),
        raising=True,
    )

    raw_signal = {
        "content": "BTO $AAPL 185c 4/18 @ 3.50",
        "author": "vinod",
        "channel": "text-trades",
        "message_id": "abc123",
    }
    config = {
        "models_dir": str(models_dir),
        "risk_params": {},
        "broker_url": "http://broker-gateway-test:8040",
        "watchlist_name": "Test Watchlist",
    }

    result = await live_pipeline.process_signal(raw_signal, config)

    assert result["decision"] == "WATCHLIST"
    assert result["reason"] == "ml_bypass_test_channel"
    assert watchlist_calls == [("AAPL", "Test Watchlist", "http://broker-gateway-test:8040")]
    inference_step = next(s for s in result["steps"] if s["step"] == "inference")
    assert inference_step["status"] == "bypassed"
    wl_step = next(s for s in result["steps"] if s["step"] == "watchlist_add")
    assert wl_step["status"] == "ok"
    assert wl_step["ticker"] == "AAPL"

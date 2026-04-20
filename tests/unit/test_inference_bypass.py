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

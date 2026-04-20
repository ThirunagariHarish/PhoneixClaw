"""Tests for the expanded risk_check rules introduced in v2.0.6.

The wizard now collects six additional risk parameters (take-profit,
trailing-stop, max-concurrent-positions, per-ticker cap, min-confidence,
loss-cooldown). risk_check.py enforces the three that gate a *new* trade:

  * min_confidence_threshold  (alias of legacy confidence_threshold)
  * max_ticker_exposure_pct   (vs. portfolio.ticker_exposure)
  * max_consecutive_losses    (vs. portfolio.consecutive_losses)

Take-profit and trailing-stop are exit-side and enforced downstream, not
in pre-trade risk_check.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

LIVE_TRADER_TOOLS = Path(__file__).resolve().parents[2] / "agents" / "templates" / "live-trader-v1" / "tools"
sys.path.insert(0, str(LIVE_TRADER_TOOLS))


@pytest.fixture
def base_inputs():
    signal = {"ticker": "AAPL", "direction": "buy"}
    prediction = {"confidence": 0.80, "pattern_matches": 1}
    portfolio = {"open_positions": 0, "daily_pnl_pct": 0}
    config = {"risk_params": {}}
    return signal, prediction, portfolio, config


def test_defaults_approve_clean_signal(base_inputs):
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True


def test_min_confidence_threshold_new_name_rejects(base_inputs):
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    prediction["confidence"] = 0.50
    config["risk_params"]["min_confidence_threshold"] = 0.70
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is False
    assert result["rejection_reason"] == "confidence_ok"


def test_legacy_confidence_threshold_still_works(base_inputs):
    """Existing agents stored `confidence_threshold` — must remain honored."""
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    prediction["confidence"] = 0.50
    config["risk_params"]["confidence_threshold"] = 0.70
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is False
    assert result["rejection_reason"] == "confidence_ok"


def test_ticker_exposure_blocks_over_cap(base_inputs):
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    portfolio["ticker_exposure"] = {"AAPL": 30.0}
    config["risk_params"]["max_ticker_exposure_pct"] = 25.0
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is False
    assert result["rejection_reason"] == "ticker_exposure_ok"


def test_ticker_exposure_allows_under_cap(base_inputs):
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    portfolio["ticker_exposure"] = {"AAPL": 10.0}
    config["risk_params"]["max_ticker_exposure_pct"] = 25.0
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True


def test_ticker_exposure_ignores_other_tickers(base_inputs):
    """High exposure to MSFT should not block a new AAPL trade."""
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    portfolio["ticker_exposure"] = {"MSFT": 80.0}
    config["risk_params"]["max_ticker_exposure_pct"] = 25.0
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True


def test_ticker_exposure_missing_portfolio_field_defaults_permissive(base_inputs):
    """Agents whose portfolio snapshot predates ticker_exposure tracking
    must not be blocked — the check silently skips."""
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    config["risk_params"]["max_ticker_exposure_pct"] = 25.0
    # no portfolio["ticker_exposure"] key at all
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True


def test_consecutive_losses_blocks_after_cooldown(base_inputs):
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    portfolio["consecutive_losses"] = 3
    config["risk_params"]["max_consecutive_losses"] = 3
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is False
    assert result["rejection_reason"] == "consecutive_losses_ok"


def test_consecutive_losses_allows_under_limit(base_inputs):
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    portfolio["consecutive_losses"] = 2
    config["risk_params"]["max_consecutive_losses"] = 3
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True


def test_consecutive_losses_missing_field_defaults_permissive(base_inputs):
    """Agents without loss-streak tracking must not be blocked."""
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    config["risk_params"]["max_consecutive_losses"] = 3
    # no portfolio["consecutive_losses"]
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True


def test_old_agent_config_still_works(base_inputs):
    """Agents created before v2.0.6 only have the four original fields —
    the new checks must silently default to permissive."""
    from risk_check import check_risk
    signal, prediction, portfolio, config = base_inputs
    config["risk_params"] = {
        "confidence_threshold": 0.65,
        "max_concurrent_positions": 3,
        "max_daily_loss_pct": 3.0,
    }
    result = check_risk(signal, prediction, portfolio, config)
    assert result["approved"] is True

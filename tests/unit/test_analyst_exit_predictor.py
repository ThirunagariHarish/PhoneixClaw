"""Unit tests for analyst_exit_predictor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from shared.utils.analyst_exit_predictor import predict_analyst_exit


def test_no_profile_returns_zero():
    out = predict_analyst_exit({}, {"entry_price": 100, "side": "buy"}, 100.0)
    assert out["probability"] == 0
    assert "no_analyst_profile" in " ".join(out["reasons"]).lower() or out["reasons"]


def test_hold_time_ratio_increases_probability():
    entry = datetime.now(timezone.utc) - timedelta(hours=50)
    profile = {
        "avg_hold_hours": 20.0,
        "median_exit_pnl": 5.0,
        "exit_pnl_p25": -2.0,
        "exit_pnl_p75": 10.0,
        "avg_exit_hour": 15.0,
        "preferred_exit_dow": {},
        "drawdown_tolerance": -5.0,
        "profile_data": {"peak_exit_hours": [], "peak_exit_days": []},
    }
    pos = {
        "entry_price": 100,
        "side": "buy",
        "opened_at": entry.isoformat(),
        "ticker": "TEST",
    }
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert out["probability"] >= 25
    assert any("overstay" in r.lower() or "avg" in r.lower() for r in out["reasons"])


def test_pnl_above_p75_adds_probability():
    profile = {
        "avg_hold_hours": 100.0,
        "median_exit_pnl": 5.0,
        "exit_pnl_p25": -2.0,
        "exit_pnl_p75": 8.0,
        "preferred_exit_dow": {},
        "drawdown_tolerance": -10.0,
        "profile_data": {},
    }
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=110.0)
    assert out["probability"] >= 10


# ---- Edge case: None profile ----

def test_none_profile_returns_zero():
    out = predict_analyst_exit(None, {"entry_price": 100, "side": "buy"}, 100.0)
    assert out["probability"] == 0
    assert out["reasons"] == ["no_analyst_profile"]


def test_profile_missing_avg_hold_hours_returns_zero():
    """Profile exists but avg_hold_hours is None/0 -- treated as no profile."""
    profile = {"avg_hold_hours": None, "median_exit_pnl": 5.0}
    out = predict_analyst_exit(profile, {"entry_price": 100, "side": "buy"}, 100.0)
    assert out["probability"] == 0
    assert out["reasons"] == ["no_analyst_profile"]


def test_profile_avg_hold_hours_zero_returns_zero():
    profile = {"avg_hold_hours": 0}
    out = predict_analyst_exit(profile, {"entry_price": 100, "side": "buy"}, 100.0)
    assert out["probability"] == 0


# ---- Entry time parsing edge cases ----

def test_entry_time_as_string_iso_format():
    entry = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy", "entry_time": entry, "ticker": "TEST"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert out["signals"].get("hold_ratio") is not None
    assert out["signals"]["hold_ratio"] >= 1.0


def test_entry_time_invalid_string_gracefully_handled():
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy", "entry_time": "not-a-date", "ticker": "TEST"}
    # Should not raise -- just skip hold ratio computation
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert "hold_ratio" not in out["signals"]


def test_entry_time_naive_datetime_treated_as_utc():
    """Naive datetime (no tzinfo) should be treated as UTC."""
    entry = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=25)
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy", "entry_time": entry, "ticker": "TEST"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert out["signals"].get("hold_ratio") is not None
    assert out["signals"]["hold_ratio"] > 1.0


# ---- P&L computation for short side ----

def test_short_side_pnl_calculation():
    profile = _base_profile(avg_hold=100.0)
    profile["exit_pnl_p75"] = 5.0
    pos = {"entry_price": 100, "side": "sell", "opened_at": datetime.now(timezone.utc).isoformat()}
    # Price went down: profit for short
    out = predict_analyst_exit(profile, pos, current_price=90.0)
    assert out["signals"]["current_pnl_pct"] == 10.0


def test_short_side_loss():
    profile = _base_profile(avg_hold=100.0)
    profile["exit_pnl_p25"] = -3.0
    profile["drawdown_tolerance"] = -5.0
    pos = {"entry_price": 100, "side": "sell", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=105.0)
    assert out["signals"]["current_pnl_pct"] == -5.0


# ---- No current_price ----

def test_no_current_price_pnl_is_zero():
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=None)
    assert out["signals"]["current_pnl_pct"] == 0.0


# ---- Drawdown tolerance ----

def test_drawdown_at_limit_adds_20():
    profile = _base_profile(avg_hold=100.0)
    profile["drawdown_tolerance"] = -10.0
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=90.5)
    # pnl = -9.5%, tolerance = -10%, ratio = 0.95 > 0.9 => +20
    assert out["signals"].get("drawdown_ratio", 0) > 0.9
    assert any("drawdown limit" in r.lower() for r in out["reasons"])


def test_drawdown_tolerance_zero_no_crash():
    profile = _base_profile(avg_hold=100.0)
    profile["drawdown_tolerance"] = 0.0
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=95.0)
    # tolerance_ratio = abs(-5) / abs(0) -> 0 (guarded), no crash
    assert isinstance(out["probability"], int)


# ---- Win rate declining ----

def test_win_rate_declining_adds_probability():
    profile = _base_profile(avg_hold=100.0)
    profile["win_rate_10"] = 0.3
    profile["win_rate_20"] = 0.6
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert any("declining" in r.lower() for r in out["reasons"])


def test_win_rate_not_declining_no_reason():
    profile = _base_profile(avg_hold=100.0)
    profile["win_rate_10"] = 0.7
    profile["win_rate_20"] = 0.6
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert not any("declining" in r.lower() for r in out["reasons"])


# ---- Probability capped at 100 ----

def test_probability_capped_at_100():
    """Stack every signal to push probability well above 100; must be clamped."""
    entry = datetime.now(timezone.utc) - timedelta(hours=200)
    profile = _base_profile(avg_hold=10.0)
    profile["exit_pnl_p75"] = 1.0
    profile["exit_pnl_p25"] = -1.0
    profile["drawdown_tolerance"] = -2.0
    profile["win_rate_10"] = 0.1
    profile["win_rate_20"] = 0.8
    profile["profile_data"] = {
        "peak_exit_hours": list(range(24)),
        "peak_exit_days": list(range(7)),
    }
    profile["preferred_exit_dow"] = {str(i): 100 for i in range(7)}
    pos = {"entry_price": 100, "side": "buy", "opened_at": entry.isoformat(), "ticker": "TEST"}
    out = predict_analyst_exit(profile, pos, current_price=120.0)
    assert out["probability"] <= 100


# ---- P&L below p25 for losing position ----

def test_pnl_below_p25_adds_probability():
    profile = _base_profile(avg_hold=100.0)
    profile["exit_pnl_p25"] = -3.0
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=95.0)
    assert any("25th percentile" in r.lower() for r in out["reasons"])


# ---- P&L at median exit ----

def test_pnl_at_median_exit():
    profile = _base_profile(avg_hold=100.0)
    profile["median_exit_pnl"] = 3.0
    profile["exit_pnl_p75"] = 10.0  # Above p75 should not trigger
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=105.0)
    assert any("median exit" in r.lower() for r in out["reasons"])


# ---- Preferred exit dow as JSON string ----

def test_preferred_exit_dow_as_json_string():
    profile = _base_profile(avg_hold=100.0)
    today = datetime.now(timezone.utc).weekday()
    # Provide exit_dow as a JSON string instead of dict
    profile["preferred_exit_dow"] = f'{{"{today}": 10}}'
    profile["profile_data"] = {"peak_exit_hours": [], "peak_exit_days": [today]}
    pos = {"entry_price": 100, "side": "buy", "opened_at": datetime.now(timezone.utc).isoformat()}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    # Should parse the JSON string and use it
    assert isinstance(out["probability"], int)


# ---- Hold ratio boundary values ----

def test_hold_ratio_approaching_avg():
    """Hold ratio between 0.8 and 1.2 adds 10 probability."""
    entry = datetime.now(timezone.utc) - timedelta(hours=18)  # ~0.9 ratio with 20h avg
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy", "entry_time": entry, "ticker": "TEST"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert out["signals"]["hold_ratio"] >= 0.8
    assert any("approaching" in r.lower() for r in out["reasons"])


def test_hold_ratio_under_80_pct_no_hold_signal():
    """Hold ratio below 0.8 should not add hold-time reasons."""
    entry = datetime.now(timezone.utc) - timedelta(hours=5)  # 0.25 ratio with 20h avg
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy", "entry_time": entry, "ticker": "TEST"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert not any("avg" in r.lower() and "hold" in r.lower() for r in out["reasons"])


# ---- No entry_time at all ----

def test_no_entry_time_skips_hold_ratio():
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert "hold_ratio" not in out["signals"]


# ---- Signals dict always populated ----

def test_signals_always_has_current_pnl_pct():
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 100, "side": "buy"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert "current_pnl_pct" in out["signals"]
    assert "current_hour_et" in out["signals"]


# ---- Profile with zero entry_price ----

def test_zero_entry_price_pnl_is_zero():
    profile = _base_profile(avg_hold=20.0)
    pos = {"entry_price": 0, "side": "buy"}
    out = predict_analyst_exit(profile, pos, current_price=100.0)
    assert out["signals"]["current_pnl_pct"] == 0.0


# ---- Helper ----

def _base_profile(avg_hold: float = 20.0) -> dict:
    return {
        "avg_hold_hours": avg_hold,
        "median_exit_pnl": 5.0,
        "exit_pnl_p25": -2.0,
        "exit_pnl_p75": 10.0,
        "avg_exit_hour": None,
        "preferred_exit_dow": {},
        "drawdown_tolerance": None,
        "win_rate_10": None,
        "win_rate_20": None,
        "post_earnings_sell_rate": None,
        "profile_data": {"peak_exit_hours": [], "peak_exit_days": []},
    }

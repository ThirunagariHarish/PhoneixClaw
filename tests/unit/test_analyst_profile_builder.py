"""Unit tests for analyst_profile_builder."""

from __future__ import annotations

from datetime import datetime, timezone

from shared.utils.analyst_profile_builder import build_profile_from_trades, get_analyst_features_for_trade


def _trade(entry: str, exit_: str, pnl: float, analyst_json: str | None = None):
    return {
        "entry_time": datetime.fromisoformat(entry).replace(tzinfo=timezone.utc),
        "exit_time": datetime.fromisoformat(exit_).replace(tzinfo=timezone.utc),
        "pnl_pct": pnl,
        "entry_price": 100,
        "exit_price": 100 + pnl,
        "model_confidence": 0.7,
        "signal_raw": analyst_json or '{"author": "alice"}',
        "decision_trail": None,
        "status": "closed",
    }


def test_build_profile_from_trades_min_size():
    assert build_profile_from_trades([_trade("2024-01-01T10:00:00+00:00", "2024-01-01T12:00:00+00:00", 1.0)]) is None


def test_build_profile_from_trades_basic():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T18:00:00+00:00", -1.0),
        _trade("2024-01-03T11:00:00+00:00", "2024-01-03T15:00:00+00:00", 3.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["total_trades"] == 3
    assert p["win_rate_10"] is not None
    assert "profile_data" in p


def test_get_analyst_features_for_trade():
    profile = {
        "win_rate_10": 0.6,
        "win_rate_20": 0.55,
        "avg_hold_hours": 24.0,
        "median_exit_pnl": 2.0,
        "exit_pnl_p25": -1.0,
        "exit_pnl_p75": 4.0,
        "avg_entry_hour": 10.0,
        "avg_exit_hour": 15.0,
        "preferred_exit_dow": {"0": 2, "4": 5},
        "drawdown_tolerance": -3.0,
        "conviction_score": 0.65,
        "post_earnings_sell_rate": None,
    }
    trade = {
        "entry_time": datetime.now(timezone.utc),
        "pnl_pct": 1.0,
    }
    feats = get_analyst_features_for_trade(profile, trade)
    assert "analyst_rolling_win_rate_10" in feats
    assert "analyst_hold_time_ratio" in feats


# ---- Edge case: empty trade list ----

def test_build_profile_empty_trade_list():
    assert build_profile_from_trades([]) is None


# ---- Edge case: exactly 2 trades (below threshold of 3) ----

def test_build_profile_two_trades_returns_none():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.0),
    ]
    assert build_profile_from_trades(trades) is None


# ---- Exactly 3 closed trades (minimum threshold) ----

def test_build_profile_exactly_three_trades():
    trades = [
        _trade("2024-01-01T09:00:00+00:00", "2024-01-01T11:00:00+00:00", 1.5),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T13:00:00+00:00", -0.5),
        _trade("2024-01-03T14:00:00+00:00", "2024-01-03T16:00:00+00:00", 2.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["total_trades"] == 3
    assert p["avg_hold_hours"] is not None
    assert p["profile_data"]["pnl_std"] > 0


# ---- Trades without exit_time are excluded from closed set ----

def test_open_trades_excluded():
    open_trade = {
        "entry_time": datetime.fromisoformat("2024-01-01T10:00:00").replace(tzinfo=timezone.utc),
        "exit_time": None,
        "pnl_pct": None,
        "entry_price": 100,
        "exit_price": None,
        "model_confidence": 0.7,
        "signal_raw": '{"author": "alice"}',
        "decision_trail": None,
        "status": "open",
    }
    closed = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.0),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 3.0),
    ]
    p = build_profile_from_trades([open_trade] + closed)
    assert p is not None
    # total_trades includes open, but profile stats from closed only
    assert p["total_trades"] == 4


# ---- All winning trades ----

def test_all_winning_trades():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", 1.5),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 3.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["win_rate_10"] == 1.0
    assert p["win_rate_20"] == 1.0
    # No losing trades -> default drawdown tolerance of -5.0
    assert p["drawdown_tolerance"] == -5.0
    assert p["profile_data"]["lose_streak_max"] == 0
    assert p["profile_data"]["win_streak_max"] == 3


# ---- All losing trades ----

def test_all_losing_trades():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", -2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.5),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", -3.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["win_rate_10"] == 0.0
    assert p["win_rate_20"] == 0.0
    assert p["drawdown_tolerance"] < 0
    assert p["profile_data"]["win_streak_max"] == 0
    assert p["profile_data"]["lose_streak_max"] == 3


# ---- Mixed trades with streak tracking ----

def test_mixed_trades_streaks():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),   # W
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", 1.0),   # W
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", -1.0),  # L
        _trade("2024-01-04T10:00:00+00:00", "2024-01-04T14:00:00+00:00", -2.0),  # L
        _trade("2024-01-05T10:00:00+00:00", "2024-01-05T14:00:00+00:00", -0.5),  # L
        _trade("2024-01-06T10:00:00+00:00", "2024-01-06T14:00:00+00:00", 3.0),   # W
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["profile_data"]["win_streak_max"] == 2
    assert p["profile_data"]["lose_streak_max"] == 3


# ---- Profile data JSON round-trip ----

def test_profile_data_json_round_trip():
    import json
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.0),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 3.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    serialized = json.dumps(p)
    deserialized = json.loads(serialized)
    assert deserialized["total_trades"] == p["total_trades"]
    assert deserialized["profile_data"]["pnl_std"] == p["profile_data"]["pnl_std"]
    assert deserialized["win_rate_10"] == p["win_rate_10"]


# ---- updated_at is set ----

def test_profile_has_updated_at():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.0),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 3.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert "updated_at" in p
    # Should be a valid ISO timestamp
    dt = datetime.fromisoformat(p["updated_at"])
    assert dt.tzinfo is not None


# ---- Percentile and statistical fields ----

def test_profile_percentiles():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", -5.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", 0.0),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 10.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["exit_pnl_p25"] <= p["median_exit_pnl"] <= p["exit_pnl_p75"]


# ---- Conviction score from model_confidence ----

def test_conviction_score_uses_model_confidence():
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.0),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 3.0),
    ]
    # All have model_confidence=0.7
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["conviction_score"] == 0.7


def test_no_model_confidence_gives_none():
    trades = []
    for i, pnl in enumerate([2.0, -1.0, 3.0]):
        t = _trade(f"2024-01-0{i+1}T10:00:00+00:00", f"2024-01-0{i+1}T14:00:00+00:00", pnl)
        t["model_confidence"] = None
        trades.append(t)
    p = build_profile_from_trades(trades)
    assert p is not None
    assert p["conviction_score"] is None


# ---- Exit day-of-week tracking ----

def test_exit_dow_tracking():
    """Trades on known days should be reflected in preferred_exit_dow."""
    # 2024-01-01 = Monday (0), 2024-01-02 = Tuesday (1), 2024-01-03 = Wednesday (2)
    trades = [
        _trade("2024-01-01T10:00:00+00:00", "2024-01-01T14:00:00+00:00", 2.0),
        _trade("2024-01-02T10:00:00+00:00", "2024-01-02T14:00:00+00:00", -1.0),
        _trade("2024-01-03T10:00:00+00:00", "2024-01-03T14:00:00+00:00", 3.0),
    ]
    p = build_profile_from_trades(trades)
    assert p is not None
    assert 0 in p["preferred_exit_dow"]  # Monday
    assert 1 in p["preferred_exit_dow"]  # Tuesday
    assert 2 in p["preferred_exit_dow"]  # Wednesday


# ---- get_analyst_features_for_trade edge cases ----

def test_features_empty_profile():
    feats = get_analyst_features_for_trade({}, {})
    assert feats == {}


def test_features_none_profile():
    feats = get_analyst_features_for_trade(None, {})
    assert feats == {}


def test_features_preferred_exit_dow_as_json_string():
    profile = {
        "win_rate_10": 0.5,
        "win_rate_20": 0.5,
        "avg_hold_hours": None,
        "median_exit_pnl": None,
        "exit_pnl_p25": None,
        "exit_pnl_p75": None,
        "avg_entry_hour": None,
        "avg_exit_hour": None,
        "preferred_exit_dow": '{"0": 3, "4": 7}',
        "drawdown_tolerance": None,
        "conviction_score": None,
        "post_earnings_sell_rate": None,
    }
    feats = get_analyst_features_for_trade(profile, {})
    assert feats["analyst_exit_dow_monday"] == 3.0
    assert feats["analyst_exit_dow_friday"] == 7.0


def test_features_pnl_vs_typical_with_zero_median():
    import numpy as np
    profile = {
        "win_rate_10": 0.5,
        "win_rate_20": 0.5,
        "avg_hold_hours": None,
        "median_exit_pnl": 0.0,
        "exit_pnl_p25": None,
        "exit_pnl_p75": None,
        "avg_entry_hour": None,
        "avg_exit_hour": None,
        "preferred_exit_dow": {},
        "drawdown_tolerance": None,
        "conviction_score": None,
        "post_earnings_sell_rate": None,
    }
    trade = {"pnl_pct": 5.0}
    feats = get_analyst_features_for_trade(profile, trade)
    # median_pnl is 0 (falsy) so pnl_vs_typical should be nan
    assert np.isnan(feats["analyst_pnl_vs_typical"])


# ---- _extract_analyst_name ----

def test_extract_analyst_from_decision_trail():
    from shared.utils.analyst_profile_builder import _extract_analyst_name
    trade = {"decision_trail": {"analyst": "Bob"}, "signal_raw": ""}
    assert _extract_analyst_name(trade) == "Bob"


def test_extract_analyst_from_decision_trail_string():
    import json

    from shared.utils.analyst_profile_builder import _extract_analyst_name
    trade = {"decision_trail": json.dumps({"author": "Charlie"}), "signal_raw": ""}
    assert _extract_analyst_name(trade) == "Charlie"


def test_extract_analyst_from_signal_raw():
    from shared.utils.analyst_profile_builder import _extract_analyst_name
    trade = {"decision_trail": None, "signal_raw": '{"username": "Dave"}'}
    assert _extract_analyst_name(trade) == "Dave"


def test_extract_analyst_none_when_missing():
    from shared.utils.analyst_profile_builder import _extract_analyst_name
    trade = {"decision_trail": None, "signal_raw": ""}
    assert _extract_analyst_name(trade) is None


def test_extract_analyst_from_parsed_signal():
    from shared.utils.analyst_profile_builder import _extract_analyst_name
    trade = {
        "decision_trail": {"parsed_signal": {"author": "Eve"}},
        "signal_raw": "",
    }
    assert _extract_analyst_name(trade) == "Eve"


def test_extract_analyst_invalid_json_decision_trail():
    from shared.utils.analyst_profile_builder import _extract_analyst_name
    trade = {"decision_trail": "not-valid-json{{{", "signal_raw": ""}
    assert _extract_analyst_name(trade) is None


# ---- _peak_hours and _peak_days ----

def test_peak_hours_empty():
    from shared.utils.analyst_profile_builder import _peak_hours
    assert _peak_hours([]) == []


def test_peak_hours_returns_top_3():
    from shared.utils.analyst_profile_builder import _peak_hours
    hours = [10.0, 10.5, 10.2, 14.0, 14.3, 15.0]
    result = _peak_hours(hours)
    assert len(result) <= 3
    assert 10 in result  # Most frequent


def test_peak_days_empty():
    from shared.utils.analyst_profile_builder import _peak_days
    assert _peak_days({}) == []


def test_max_streak_empty():
    from shared.utils.analyst_profile_builder import _max_streak
    assert _max_streak([]) == 0


def test_max_streak_all_ones():
    from shared.utils.analyst_profile_builder import _max_streak
    assert _max_streak([1, 1, 1, 1]) == 4


def test_max_streak_all_zeros():
    from shared.utils.analyst_profile_builder import _max_streak
    assert _max_streak([0, 0, 0]) == 0

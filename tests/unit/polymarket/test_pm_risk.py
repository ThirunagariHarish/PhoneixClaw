"""Unit tests for PolymarketLayerRisk (Phase 6).

These exercise every branch of the PM risk layer plus its integration into
`RiskCheckChain`. The layer is pure: state is passed in as a dict, no DB.
"""

from __future__ import annotations

from services.execution.src.risk_chain import (
    PolymarketLayerRisk,
    RiskCheckChain,
)


def _intent(**overrides):
    base = {
        "venue": "polymarket",
        "mode": "PAPER",
        "qty_shares": 100,
        "limit_price": 0.40,  # notional = $40, well under $100 cap
    }
    base.update(overrides)
    return base


def _state(**overrides):
    base = {
        "strategy_mode": "PAPER",
        "bankroll_usd": 5000.0,
        "max_strategy_notional_usd": 1000.0,
        "max_trade_notional_usd": 100.0,
        "kelly_cap": 0.25,
        "open_strategy_notional_usd": 0.0,
        "attestation_valid": True,
        "f9_tradeable": True,
        "f9_score": 0.10,
        "f9_threshold": 0.55,
    }
    base.update(overrides)
    return base


def test_pm_layer_happy_path():
    res = PolymarketLayerRisk().check(_intent(), _state())
    assert res["passed"] is True
    assert res["layer"] == "polymarket"


def test_pm_layer_mode_mismatch_hard_fail():
    res = PolymarketLayerRisk().check(_intent(mode="LIVE"), _state(strategy_mode="PAPER"))
    assert res["passed"] is False
    assert "pm_mode_mismatch" in res["reason"]


def test_pm_layer_invalid_mode():
    res = PolymarketLayerRisk().check(_intent(mode="DEMO"), _state())
    assert res["passed"] is False
    assert "pm_mode_invalid" in res["reason"]


def test_pm_layer_jurisdiction_gate():
    res = PolymarketLayerRisk().check(_intent(), _state(attestation_valid=False))
    assert res["passed"] is False
    assert "jurisdiction" in res["reason"]


def test_pm_layer_f9_not_tradeable():
    res = PolymarketLayerRisk().check(_intent(), _state(f9_tradeable=False))
    assert res["passed"] is False
    assert "pm_f9_not_tradeable" in res["reason"]


def test_pm_layer_f9_above_threshold():
    res = PolymarketLayerRisk().check(_intent(), _state(f9_score=0.80))
    assert res["passed"] is False
    assert "pm_f9_score_above_threshold" in res["reason"]


def test_pm_layer_per_trade_cap():
    # qty 300 * 0.40 = $120 > $100 cap
    res = PolymarketLayerRisk().check(_intent(qty_shares=300), _state())
    assert res["passed"] is False
    assert "pm_per_trade_cap_exceeded" in res["reason"]


def test_pm_layer_per_strategy_cap():
    res = PolymarketLayerRisk().check(
        _intent(),
        _state(open_strategy_notional_usd=980.0),  # 980 + 40 = 1020 > 1000
    )
    assert res["passed"] is False
    assert "pm_per_strategy_cap_exceeded" in res["reason"]


def test_pm_layer_bankroll_cap():
    # Loosen the strategy cap so the bankroll branch is reached.
    res = PolymarketLayerRisk().check(
        _intent(),
        _state(
            max_strategy_notional_usd=1_000_000.0,
            bankroll_usd=4990.0,
            open_strategy_notional_usd=4980.0,
        ),
    )
    assert res["passed"] is False
    assert "pm_bankroll_exceeded" in res["reason"]


def test_pm_layer_kelly_cap():
    intent = _intent()
    intent["kelly_fraction"] = 0.30
    res = PolymarketLayerRisk().check(intent, _state())
    assert res["passed"] is False
    assert "pm_kelly_cap_exceeded" in res["reason"]


def test_pm_layer_kelly_within_cap():
    intent = _intent()
    intent["kelly_fraction"] = 0.20
    res = PolymarketLayerRisk().check(intent, _state())
    assert res["passed"] is True


def test_pm_layer_price_out_of_range():
    res = PolymarketLayerRisk().check(_intent(limit_price=1.5), _state())
    assert res["passed"] is False
    assert "pm_price_out_of_range" in res["reason"]


def test_pm_layer_qty_or_price_non_positive():
    res = PolymarketLayerRisk().check(_intent(qty_shares=0), _state())
    assert res["passed"] is False
    assert "non_positive" in res["reason"]


def test_chain_routes_pm_intent_through_pm_layer():
    chain = RiskCheckChain()
    out = chain.evaluate(
        _intent(),
        agent_state={"open_positions": 0, "daily_trades": 0},
        global_state={"total_exposure": 0},
        pm_state=_state(),
    )
    assert out["approved"] is True
    layers = [c["layer"] for c in out["checks"]]
    assert "polymarket" in layers


def test_chain_blocks_pm_intent_on_mode_mismatch():
    chain = RiskCheckChain()
    out = chain.evaluate(
        _intent(mode="LIVE"),
        agent_state={"open_positions": 0, "daily_trades": 0},
        global_state={"total_exposure": 0},
        pm_state=_state(strategy_mode="PAPER"),
    )
    assert out["approved"] is False
    assert "pm_mode_mismatch" in out["reason"]


def test_chain_skips_pm_layer_for_non_pm_intent():
    chain = RiskCheckChain()
    out = chain.evaluate(
        {"venue": "alpaca", "qty": 1, "limit_price": 100.0},
        agent_state={"open_positions": 0, "daily_trades": 0},
        global_state={"total_exposure": 0},
    )
    assert out["approved"] is True
    layers = [c["layer"] for c in out["checks"]]
    assert "polymarket" not in layers


def test_chain_fails_closed_when_pm_fields_present_without_venue_tag():
    # B3 regression: if an intent carries a PM-shaped field (pm_market_id
    # or pm_strategy_id) but the caller forgot to set venue=polymarket AND
    # no pm_state was supplied, the chain must reject rather than silently
    # skip the PM layer.
    chain = RiskCheckChain()
    out = chain.evaluate(
        {
            "venue": "alpaca",  # wrong tag
            "pm_strategy_id": "some-strat",
            "pm_market_id": "some-mkt",
            "qty": 1,
            "limit_price": 0.5,
        },
        agent_state={"open_positions": 0, "daily_trades": 0},
        global_state={"total_exposure": 0},
    )
    assert out["approved"] is False
    assert "pm_intent_missing_venue_tag" in out["reason"]


def test_chain_rejects_tampered_intent_mode_when_repo_disagrees():
    # M7: risk chain must read mode from DB (repo callable), not trust the
    # intent. A tampered intent claiming PAPER when the DB says LIVE is
    # rejected.
    def repo(_pm_strategy_id):
        return "LIVE"

    chain = RiskCheckChain(pm_strategy_repo=repo)
    out = chain.evaluate(
        _intent(mode="PAPER", pm_strategy_id="strat-1"),
        agent_state={"open_positions": 0, "daily_trades": 0},
        global_state={"total_exposure": 0},
        pm_state=_state(strategy_mode="PAPER"),
    )
    assert out["approved"] is False
    assert "pm_mode_intent_db_mismatch" in out["reason"]


def test_chain_accepts_intent_when_repo_mode_matches():
    def repo(_pm_strategy_id):
        return "PAPER"

    chain = RiskCheckChain(pm_strategy_repo=repo)
    out = chain.evaluate(
        _intent(pm_strategy_id="strat-1"),
        agent_state={"open_positions": 0, "daily_trades": 0},
        global_state={"total_exposure": 0},
        pm_state=_state(),
    )
    assert out["approved"] is True

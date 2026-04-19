"""Tests for decision fuser."""


from services.pipeline_worker.src.pipeline.decision_fuser import Decision, fuse


def _base_inputs(
    market_open: bool = True,
    pred: str = "TRADE",
    confidence: float = 0.8,
    risk_approved: bool = True,
    ta_bias: str = "neutral",
    ta_adj: float = 0.0,
    direction: str = "buy",
):
    signal = {"ticker": "AAPL", "direction": direction}
    prediction = {"prediction": pred, "confidence": confidence}
    risk = {"approved": risk_approved, "reason": "" if risk_approved else "max_positions"}
    ta = {"overall_bias": ta_bias, "confidence_adjustment": ta_adj}
    market = {"is_open": market_open, "session_type": "regular" if market_open else "closed"}
    config = {"risk_params": {"confidence_threshold": 0.6}, "default_qty": 1}
    return signal, prediction, risk, ta, market, config


class TestFuse:
    def test_market_closed_returns_watchlist(self):
        args = _base_inputs(market_open=False)
        decision = fuse(*args)
        assert decision.action == "WATCHLIST"
        assert "closed" in decision.reasons[0].lower() or "Market" in decision.reasons[0]

    def test_skip_low_confidence_returns_watchlist(self):
        args = _base_inputs(pred="SKIP", confidence=0.3)
        decision = fuse(*args)
        assert decision.action == "WATCHLIST"

    def test_risk_rejected_returns_reject(self):
        args = _base_inputs(risk_approved=False)
        decision = fuse(*args)
        assert decision.action == "REJECT"

    def test_trade_approved_neutral_ta(self):
        args = _base_inputs(ta_bias="neutral")
        decision = fuse(*args)
        assert decision.action == "EXECUTE"
        assert decision.execution_params is not None
        assert decision.execution_params["symbol"] == "AAPL"
        assert decision.execution_params["side"] == "buy"

    def test_trade_ta_aligns_boosts_confidence(self):
        args = _base_inputs(ta_bias="bullish", ta_adj=0.1, confidence=0.7)
        decision = fuse(*args)
        assert decision.action == "EXECUTE"
        assert decision.final_confidence > 0.7

    def test_trade_ta_opposes_returns_watchlist(self):
        args = _base_inputs(ta_bias="bearish", ta_adj=-0.15, direction="buy")
        decision = fuse(*args)
        assert decision.action == "WATCHLIST"

    def test_sell_direction_execution_params(self):
        args = _base_inputs(direction="sell", ta_bias="bearish", ta_adj=0.1)
        decision = fuse(*args)
        assert decision.action == "EXECUTE"
        assert decision.execution_params["side"] == "sell"

    def test_skip_with_high_confidence_returns_watchlist(self):
        args = _base_inputs(pred="SKIP", confidence=0.9)
        decision = fuse(*args)
        assert decision.action == "WATCHLIST"

    def test_confidence_capped_at_one(self):
        args = _base_inputs(ta_bias="bullish", ta_adj=0.2, confidence=0.95)
        decision = fuse(*args)
        assert decision.final_confidence <= 1.0

    def test_decision_dataclass(self):
        d = Decision(action="REJECT")
        assert d.final_confidence == 0.0
        assert d.reasons == []
        assert d.execution_params is None

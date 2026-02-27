from services.option_chain_analyzer.src.analyzer import _score_contract
from services.option_chain_analyzer.src.strategy_suggester import suggest_strategy
from shared.unusual_whales.models import OptionContract


class TestOptionAnalyzer:
    def _make_contract(self, **overrides) -> OptionContract:
        defaults = {
            "ticker": "SPY",
            "strike": 200.0,
            "option_type": "CALL",
            "expiration": "2026-03-20",
            "open_interest": 5000,
            "delta": 0.45,
            "implied_volatility": 0.25,
            "bid": 3.00,
            "ask": 3.20,
        }
        defaults.update(overrides)
        return OptionContract(**defaults)

    def test_contract_scoring(self):
        contract = self._make_contract()
        score = _score_contract(contract, "bullish", gex_level=0)
        assert isinstance(score, float)
        assert score > 0

    def test_low_oi_penalized(self):
        high_oi = self._make_contract(open_interest=10000)
        low_oi = self._make_contract(open_interest=50)
        assert _score_contract(high_oi, "bullish") > _score_contract(low_oi, "bullish")

    def test_wide_spread_penalized(self):
        tight = self._make_contract(bid=3.00, ask=3.05)
        wide = self._make_contract(bid=2.00, ask=4.00)
        assert _score_contract(tight, "bullish") > _score_contract(wide, "bullish")


class TestStrategySuggester:
    def test_high_iv_suggests_spread(self):
        result = suggest_strategy("SPY", "bullish", iv_percentile=85.0)
        assert len(result) > 0
        assert any("spread" in s["strategy"].lower() or "put" in s["strategy"].lower() for s in result)

    def test_low_iv_suggests_long(self):
        result = suggest_strategy("SPY", "bullish", iv_percentile=15.0)
        assert len(result) > 0
        assert any("long" in s["strategy"].lower() or "debit" in s["strategy"].lower() for s in result)

    def test_neutral_suggests_condor(self):
        result = suggest_strategy("AAPL", "neutral")
        assert len(result) > 0
        assert any("condor" in s["strategy"].lower() for s in result)

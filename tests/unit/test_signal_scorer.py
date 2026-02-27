import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from services.signal_scorer.src.scorer import SignalScorerService


class TestSignalQuality:
    def setup_method(self):
        with patch.object(SignalScorerService, '__init__', lambda self: None):
            self.scorer = SignalScorerService()
            self.scorer._last_breakdown = {}

    def test_full_quality_signal(self):
        signal = {
            "price": 2.50,
            "expiration": "2025-03-21",
            "strike": 190,
            "quantity": 1,
            "profit_target": 0.30,
        }
        assert self.scorer._score_signal_quality(signal) == 30

    def test_minimal_signal(self):
        signal = {}
        assert self.scorer._score_signal_quality(signal) == 0

    def test_partial_signal(self):
        signal = {"price": 2.50, "strike": 190}
        assert self.scorer._score_signal_quality(signal) == 13


class TestMarketConditions:
    def setup_method(self):
        with patch.object(SignalScorerService, '__init__', lambda self: None):
            self.scorer = SignalScorerService()

    def test_market_open(self):
        self.scorer.calendar = MagicMock()
        self.scorer.calendar.is_market_open.return_value = True
        assert self.scorer._score_market_conditions() == 18

    def test_market_closed(self):
        self.scorer.calendar = MagicMock()
        self.scorer.calendar.is_market_open.return_value = False
        assert self.scorer._score_market_conditions() == 8

"""Tests for agents/analyst/tools/score_trade_setup.py"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from agents.analyst.tools.score_trade_setup import score_trade_setup
from agents.analyst.personas.library import PERSONA_LIBRARY


def make_bullish():
    return {"signal": "bullish"}


def make_bearish():
    return {"signal": "bearish"}


def make_neutral():
    return {"signal": "neutral"}


def test_all_bullish_signals_above_threshold():
    persona = PERSONA_LIBRARY["aggressive_momentum"]
    result = score_trade_setup(
        ticker="SPY",
        persona_config={"tool_weights": persona.tool_weights, "signal_filters": persona.signal_filters},
        chart_signal=make_bullish(),
        options_signal=make_bullish(),
        sentiment_signal=make_bullish(),
    )
    assert result["confidence"] > 50
    assert result["recommendation"] == "buy"


def test_all_bearish_signals():
    persona = PERSONA_LIBRARY["conservative_swing"]
    result = score_trade_setup(
        ticker="SPY",
        persona_config={"tool_weights": persona.tool_weights, "signal_filters": {}},
        chart_signal=make_bearish(),
        options_signal=make_bearish(),
        sentiment_signal=make_bearish(),
    )
    assert result["recommendation"] == "sell"


def test_all_neutral_returns_neutral():
    persona = PERSONA_LIBRARY["balanced"]
    result = score_trade_setup(
        ticker="AAPL",
        persona_config={"tool_weights": persona.tool_weights, "signal_filters": {}},
        chart_signal=make_neutral(),
        options_signal=make_neutral(),
        sentiment_signal=make_neutral(),
    )
    assert result["recommendation"] == "neutral"


def test_confidence_is_0_to_100():
    persona = PERSONA_LIBRARY["scalper"]
    result = score_trade_setup(
        ticker="TSLA",
        persona_config={"tool_weights": persona.tool_weights, "signal_filters": {}},
        chart_signal=make_bullish(),
        options_signal=make_neutral(),
        sentiment_signal=make_bearish(),
    )
    assert 0 <= result["confidence"] <= 100

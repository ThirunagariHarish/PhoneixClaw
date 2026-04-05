"""
End-to-end tests for the Trading Vision implementation.
Tests the full flow: connector tags, agent creation, backtesting pipeline,
signal parsing, pattern engine, and live pipeline.
"""

import uuid
from datetime import datetime, timezone

import pytest

# ── Test 1: Connector tags ─────────────────────────────────────────────────

def test_connector_model_has_tags():
    """Connector model should have a tags field."""
    from shared.db.models.connector import Connector
    assert hasattr(Connector, "tags"), "Connector model must have 'tags' field"


def test_connector_response_includes_tags():
    """ConnectorResponse schema should include tags."""
    from apps.api.src.routes.connectors import ConnectorResponse
    fields = ConnectorResponse.model_fields
    assert "tags" in fields, "ConnectorResponse must include 'tags' field"


def test_connector_create_accepts_tags():
    """ConnectorCreate schema should accept tags."""
    from apps.api.src.routes.connectors import ConnectorCreate
    c = ConnectorCreate(name="test", type="discord", tags=["signals", "news"])
    assert c.tags == ["signals", "news"]


# ── Test 2: Agent type rename ──────────────────────────────────────────────

def test_agent_create_accepts_trend_type():
    """AgentCreate should accept 'trend' as a valid type."""
    from apps.api.src.routes.agents import AgentCreate
    a = AgentCreate(name="test", type="trend", instance_id="")
    assert a.type == "trend"


def test_agent_create_still_accepts_sentiment():
    """Backward compat: 'sentiment' should still be accepted."""
    from apps.api.src.routes.agents import AgentCreate
    a = AgentCreate(name="test", type="sentiment", instance_id="")
    assert a.type == "sentiment"


def test_agent_instance_id_optional():
    """Instance ID should be optional (empty string or managed)."""
    from apps.api.src.routes.agents import AgentCreate
    a = AgentCreate(name="test", type="trading", instance_id="")
    assert a.instance_id == ""


# ── Test 3: Channel message model ─────────────────────────────────────────

def test_channel_message_model():
    """ChannelMessage model should have all required fields."""
    from shared.db.models.channel_message import ChannelMessage
    for field in ["connector_id", "channel", "author", "content", "message_type",
                  "tickers_mentioned", "platform_message_id", "posted_at"]:
        assert hasattr(ChannelMessage, field), f"ChannelMessage missing field: {field}"


def test_backtest_trade_model():
    """BacktestTrade model should have all enrichment fields."""
    from shared.db.models.backtest_trade import BacktestTrade
    enrichment_fields = [
        "entry_rsi", "entry_macd", "entry_bollinger_position",
        "entry_volume_ratio", "entry_atr", "market_vix",
        "hour_of_day", "day_of_week", "is_pre_market",
        "option_flow_sentiment", "gex_level", "pattern_tags",
    ]
    for field in enrichment_fields:
        assert hasattr(BacktestTrade, field), f"BacktestTrade missing field: {field}"


# ── Test 4: Signal parser ─────────────────────────────────────────────────

def test_signal_parser_buy():
    """Signal parser should detect buy signals."""
    from shared.nlp.signal_parser import parse_signal
    result = parse_signal("BUY $AAPL at $150 call")
    assert result.signal_type == "buy_signal"
    assert "AAPL" in result.tickers
    assert result.price == 150.0


def test_signal_parser_sell():
    """Signal parser should detect sell signals."""
    from shared.nlp.signal_parser import parse_signal
    result = parse_signal("Sold $TSLA for +30% STC")
    assert result.signal_type in ("sell_signal", "close_signal")
    assert "TSLA" in result.tickers


def test_signal_parser_noise():
    """Signal parser should classify noise messages."""
    from shared.nlp.signal_parser import parse_signal
    result = parse_signal("good morning everyone how are you doing today")
    assert result.signal_type in ("noise", "info")
    assert len(result.tickers) == 0


def test_signal_parser_close():
    """Signal parser should detect close signals."""
    from shared.nlp.signal_parser import parse_signal
    result = parse_signal("Closed $SPY position, took profit at $450")
    assert result.signal_type == "close_signal"
    assert "SPY" in result.tickers


def test_trade_pairing():
    """pair_trades should match buy and sell signals for the same ticker."""
    from shared.nlp.signal_parser import pair_trades, MessageSignal, ParsedSignal
    signals = [
        MessageSignal(
            message_id="1", author="trader", content="BUY $AAPL",
            posted_at=datetime(2024, 1, 1, 10, 0, tzinfo=timezone.utc),
            parsed=ParsedSignal(signal_type="buy_signal", tickers=["AAPL"], primary_ticker="AAPL", price=150.0),
        ),
        MessageSignal(
            message_id="2", author="trader", content="SOLD $AAPL",
            posted_at=datetime(2024, 1, 1, 14, 0, tzinfo=timezone.utc),
            parsed=ParsedSignal(signal_type="sell_signal", tickers=["AAPL"], primary_ticker="AAPL", price=160.0),
        ),
    ]
    trades = pair_trades(signals)
    assert len(trades) == 1
    assert trades[0].ticker == "AAPL"
    assert trades[0].entry_signal.message_id == "1"
    assert trades[0].exit_signal.message_id == "2"


# ── Test 5: Pattern engine ────────────────────────────────────────────────

def test_pattern_engine_empty():
    """Pattern engine should handle empty trade list."""
    from services.backtest_runner.src.pattern_engine import analyze_patterns
    result = analyze_patterns([])
    assert result["rules"] == []
    assert result["overall_channel_metrics"] == {}


def test_pattern_engine_basic():
    """Pattern engine should discover time-based patterns."""
    from services.backtest_runner.src.pattern_engine import analyze_patterns

    class FakeTrade:
        """Lightweight stand-in for BacktestTrade ORM object."""
        pass

    trades = []
    for i in range(20):
        t = FakeTrade()
        t.ticker = "SPY"
        t.side = "long"
        t.entry_price = 450
        t.exit_price = 460 if i % 3 != 0 else 440
        t.pnl = t.exit_price - t.entry_price
        t.pnl_pct = (t.pnl / t.entry_price) * 100
        t.is_profitable = t.pnl > 0
        t.hour_of_day = 10 if i < 10 else 14
        t.day_of_week = i % 5
        t.is_pre_market = False
        t.entry_rsi = 50 + i
        t.entry_macd = None
        t.entry_bollinger_position = None
        t.entry_volume_ratio = 1.0 + i * 0.1
        t.market_vix = 18.0
        t.market_spy_change = 0.5
        t.entry_atr = None
        t.entry_sma_20_distance = None
        t.entry_sma_50_distance = None
        t.entry_vwap_distance = None
        t.gex_level = None
        t.option_flow_sentiment = None
        t.pattern_tags = []
        trades.append(t)

    result = analyze_patterns(trades)
    assert "rules" in result
    assert "overall_channel_metrics" in result
    metrics = result["overall_channel_metrics"]
    assert metrics["total_trades_identified"] == 20
    assert metrics["overall_win_rate"] > 0


# ── Test 6: Intelligence filter ───────────────────────────────────────────

def test_intelligence_filter_pass():
    """Intelligence filter should pass signals matching positive rules."""
    from services.execution.src.live_pipeline import IntelligenceFilter
    rules = [
        {"name": "morning", "condition": "hour_of_day between 9 and 11", "weight": 0.8},
        {"name": "spy_only", "condition": "ticker == 'SPY'", "weight": 0.5},
    ]
    f = IntelligenceFilter(rules, threshold=0.0)
    passed, score, matched = f.evaluate({"hour_of_day": 10, "ticker": "SPY"})
    assert passed
    assert score > 0
    assert len(matched) == 2


def test_intelligence_filter_reject():
    """Intelligence filter should reject when score is below threshold."""
    from services.execution.src.live_pipeline import IntelligenceFilter
    rules = [
        {"name": "high_rsi_avoid", "condition": "entry_rsi > 80", "weight": -0.8},
    ]
    f = IntelligenceFilter(rules, threshold=0.0)
    passed, score, matched = f.evaluate({"entry_rsi": 85})
    assert not passed
    assert score < 0


def test_intelligence_filter_no_rules():
    """Intelligence filter with no rules should pass everything."""
    from services.execution.src.live_pipeline import IntelligenceFilter
    f = IntelligenceFilter([], threshold=0.0)
    passed, score, matched = f.evaluate({"ticker": "AAPL"})
    assert passed


# ── Test 7: Live pipeline ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_live_pipeline_process():
    """Live pipeline should process a message end-to-end."""
    from services.execution.src.live_pipeline import LiveTradingPipeline
    pipeline = LiveTradingPipeline(
        agent_id="test-agent",
        agent_config={"max_position_pct": 10},
        intelligence_rules=[
            {"name": "all_pass", "condition": "ticker == 'SPY'", "weight": 1.0},
        ],
    )
    result = await pipeline.process_message(
        content="BUY $SPY at $450",
        author="trader",
        channel="signals",
    )
    assert result is not None
    assert result["action"] == "simulated"
    assert result["intent"]["symbol"] == "SPY"


@pytest.mark.asyncio
async def test_live_pipeline_noise():
    """Live pipeline should ignore noise messages."""
    from services.execution.src.live_pipeline import LiveTradingPipeline
    pipeline = LiveTradingPipeline(
        agent_id="test-agent",
        agent_config={},
        intelligence_rules=[],
    )
    result = await pipeline.process_message(
        content="hey what's up everyone",
        author="random",
        channel="general",
    )
    assert result is None

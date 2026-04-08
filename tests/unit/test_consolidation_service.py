"""Unit tests for ConsolidationService logic (no DB required)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

try:
    from apps.api.src.services.consolidation_service import (
        _MIN_OBSERVATIONS_FOR_PATTERN,
        ConsolidationService,
    )
    from shared.db.models.wiki import AgentWikiEntry
except Exception as e:
    pytest.skip(f"Cannot import consolidation_service: {e}", allow_module_level=True)


# ---------------------------------------------------------------------------
# Helpers to build fake wiki entries
# ---------------------------------------------------------------------------


def _make_entry(title: str, content: str = "", confidence: float = 0.6) -> AgentWikiEntry:
    e = AgentWikiEntry()
    e.id = uuid.uuid4()
    e.agent_id = uuid.uuid4()
    e.category = "TRADE_OBSERVATION"
    e.title = title
    e.content = content
    e.tags = []
    e.symbols = ["AAPL"]
    e.confidence_score = confidence
    e.trade_ref_ids = []
    e.created_by = "agent"
    e.is_active = True
    e.is_shared = False
    e.version = 1
    e.created_at = datetime.now(timezone.utc)
    e.updated_at = datetime.now(timezone.utc)
    return e


def _make_service() -> ConsolidationService:
    """Return a ConsolidationService with a dummy session (no DB needed for pure-logic tests)."""

    class _FakeSession:
        pass

    return ConsolidationService(_FakeSession())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# _classify_observation tests
# ---------------------------------------------------------------------------


class TestClassifyObservation:
    def test_bearish_reversal_from_title(self):
        svc = _make_service()
        entry = _make_entry(title="AAPL bearish reversal at resistance", content="")
        result = svc._classify_observation(entry)
        assert "bearish_reversal" in result

    def test_bullish_breakout_from_content(self):
        svc = _make_service()
        entry = _make_entry(title="TSLA trade note", content="Bullish breakout above 200MA")
        result = svc._classify_observation(entry)
        assert "bullish_breakout" in result

    def test_support_hold(self):
        svc = _make_service()
        entry = _make_entry(title="SPY bounce off support level")
        result = svc._classify_observation(entry)
        assert "support_hold" in result

    def test_volume_spike(self):
        svc = _make_service()
        entry = _make_entry(title="Unusual volume surge on NVDA")
        result = svc._classify_observation(entry)
        assert "volume_spike" in result

    def test_gap_fill(self):
        svc = _make_service()
        entry = _make_entry(title="Opening gap fill on AMD")
        result = svc._classify_observation(entry)
        assert "gap_fill" in result

    def test_no_match_returns_empty(self):
        svc = _make_service()
        entry = _make_entry(title="Random unrelated note", content="nothing here")
        result = svc._classify_observation(entry)
        assert result == []

    def test_multiple_patterns_detected(self):
        svc = _make_service()
        entry = _make_entry(
            title="Bearish reversal at resistance with volume spike",
            content="High volume rejection at the ceiling.",
        )
        result = svc._classify_observation(entry)
        assert "bearish_reversal" in result
        assert "volume_spike" in result
        assert "resistance_reject" in result

    def test_case_insensitive(self):
        svc = _make_service()
        entry = _make_entry(title="BEARISH REVERSAL observed")
        result = svc._classify_observation(entry)
        assert "bearish_reversal" in result


# ---------------------------------------------------------------------------
# _find_patterns tests (async, no DB)
# ---------------------------------------------------------------------------


class TestFindPatterns:
    @pytest.mark.asyncio
    async def test_fewer_than_3_observations_no_pattern(self):
        svc = _make_service()
        obs = [
            _make_entry("AAPL bearish reversal"),
            _make_entry("AAPL bearish fade"),
        ]
        patterns = await svc._find_patterns(obs)
        assert patterns == [], f"Expected no patterns, got: {patterns}"

    @pytest.mark.asyncio
    async def test_3_or_more_matching_observations_returns_pattern(self):
        svc = _make_service()
        obs = [
            _make_entry("AAPL bearish reversal at resistance"),
            _make_entry("AAPL reversal rejection from highs"),
            _make_entry("AAPL fade at resistance zone"),
        ]
        # All three share symbol=AAPL and match bearish_reversal / resistance_reject clusters
        patterns = await svc._find_patterns(obs)
        assert len(patterns) >= 1, f"Expected ≥1 pattern, got: {patterns}"
        # Verify the pattern mentions the symbol
        symbols = [p["symbol"] for p in patterns]
        assert "AAPL" in symbols

    @pytest.mark.asyncio
    async def test_pattern_has_required_fields(self):
        svc = _make_service()
        obs = [
            _make_entry("TSLA bullish breakout above 200MA"),
            _make_entry("TSLA breakup confirmed with momentum"),
            _make_entry("TSLA bullish momentum surge"),
        ]
        patterns = await svc._find_patterns(obs)
        assert len(patterns) >= 1
        p = patterns[0]
        assert "symbol" in p
        assert "pattern_type" in p
        assert "count" in p
        assert "avg_confidence" in p
        assert "sample_titles" in p
        assert p["count"] >= _MIN_OBSERVATIONS_FOR_PATTERN

    @pytest.mark.asyncio
    async def test_exactly_3_observations_triggers_pattern(self):
        svc = _make_service()
        obs = [_make_entry(f"SPY support bounce {i}") for i in range(3)]
        patterns = await svc._find_patterns(obs)
        support_patterns = [p for p in patterns if p["pattern_type"] == "support_hold"]
        assert len(support_patterns) >= 1

    @pytest.mark.asyncio
    async def test_empty_observations_returns_empty(self):
        svc = _make_service()
        patterns = await svc._find_patterns([])
        assert patterns == []

    @pytest.mark.asyncio
    async def test_avg_confidence_calculated_correctly(self):
        svc = _make_service()
        obs = [
            _make_entry("MSFT volume spike surge", confidence=0.8),
            _make_entry("MSFT volume flood observed", confidence=0.6),
            _make_entry("MSFT unusual volume surge again", confidence=0.7),
        ]
        patterns = await svc._find_patterns(obs)
        vol_patterns = [p for p in patterns if p["pattern_type"] == "volume_spike"]
        assert vol_patterns
        # avg should be (0.8 + 0.6 + 0.7) / 3 = 0.7
        assert abs(vol_patterns[0]["avg_confidence"] - 0.7) < 0.01


# ---------------------------------------------------------------------------
# _generate_report tests
# ---------------------------------------------------------------------------


class TestGenerateReport:
    def test_returns_string(self):
        svc = _make_service()
        report = svc._generate_report(
            agent_id=uuid.uuid4(),
            trades_analyzed=10,
            patterns=[],
            entries_written=0,
            entries_updated=0,
            entries_pruned=2,
            rules_proposed=0,
        )
        assert isinstance(report, str)
        assert len(report) > 0

    def test_report_contains_markdown_heading(self):
        svc = _make_service()
        report = svc._generate_report(
            agent_id=uuid.uuid4(),
            trades_analyzed=5,
            patterns=[],
            entries_written=1,
            entries_updated=0,
            entries_pruned=0,
            rules_proposed=0,
        )
        assert "# Nightly Consolidation Report" in report

    def test_report_contains_stats(self):
        svc = _make_service()
        agent_id = uuid.uuid4()
        report = svc._generate_report(
            agent_id=agent_id,
            trades_analyzed=42,
            patterns=[{"symbol": "AAPL", "pattern_type": "bearish_reversal", "count": 5,
                        "avg_confidence": 0.75, "sample_titles": ["t1", "t2"]}],
            entries_written=2,
            entries_updated=1,
            entries_pruned=3,
            rules_proposed=1,
        )
        assert "42" in report
        assert "bearish_reversal" in report.lower() or "Bearish Reversal" in report
        assert "AAPL" in report
        assert "0.75" in report

    def test_report_with_no_patterns_shows_placeholder(self):
        svc = _make_service()
        report = svc._generate_report(
            agent_id=uuid.uuid4(),
            trades_analyzed=0,
            patterns=[],
            entries_written=0,
            entries_updated=0,
            entries_pruned=0,
            rules_proposed=0,
        )
        assert "No patterns detected" in report or "no patterns" in report.lower()


# ---------------------------------------------------------------------------
# is_trading_day tests
# ---------------------------------------------------------------------------


class TestIsTradingDay:
    def test_weekday_non_holiday_is_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        # 2025-01-06 is a Monday (not a holiday)
        assert is_trading_day(date(2025, 1, 6)) is True

    def test_saturday_is_not_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        assert is_trading_day(date(2025, 1, 4)) is False  # Saturday

    def test_sunday_is_not_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        assert is_trading_day(date(2025, 1, 5)) is False  # Sunday

    def test_new_years_day_is_not_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        assert is_trading_day(date(2025, 1, 1)) is False

    def test_christmas_2025_is_not_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        assert is_trading_day(date(2025, 12, 25)) is False

    def test_mlk_day_2026_is_not_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        assert is_trading_day(date(2026, 1, 19)) is False

    def test_regular_monday_2026_is_trading_day(self):
        from datetime import date

        from shared.config.market_holidays import is_trading_day

        # 2026-01-05 is a Monday; not a holiday
        assert is_trading_day(date(2026, 1, 5)) is True

"""Unit tests for the morning-briefing Polymarket section (Phase 13 / F12).

Pure-Python tests with a fake DAO. No DB, no SQLAlchemy import.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

# Load the tool module by file path because the agent template dir is not
# a Python package.
_MODULE_PATH = (
    Path(__file__).resolve().parents[2]
    / "agents"
    / "templates"
    / "morning-briefing-agent"
    / "tools"
    / "compile_pm_section.py"
)
_spec = importlib.util.spec_from_file_location("compile_pm_section", _MODULE_PATH)
assert _spec and _spec.loader
pm_mod = importlib.util.module_from_spec(_spec)
# Register before exec so @dataclass can resolve the module via
# sys.modules[cls.__module__] when introspecting types under
# `from __future__ import annotations`. Without this, dataclasses'
# _is_type() raises AttributeError on NoneType.__dict__.
sys.modules["compile_pm_section"] = pm_mod
_spec.loader.exec_module(pm_mod)


# ---------------------------------------------------------------------------
# Fake DAO
# ---------------------------------------------------------------------------

class FakeDAO:
    def __init__(
        self,
        edges=None,
        expiring=None,
        whales=None,
        positions=None,
        alerts=None,
        raise_on=None,
    ):
        self._edges = edges or []
        self._expiring = expiring or []
        self._whales = whales or []
        self._positions = positions or []
        self._alerts = alerts or []
        self._raise_on = raise_on or set()

    def _maybe_raise(self, name):
        if name in self._raise_on:
            raise RuntimeError(f"boom-{name}")

    def top_edges(self, limit):
        self._maybe_raise("edges")
        return self._edges[:limit]

    def expiring_between(self, start, end):
        self._maybe_raise("expiring")
        return [m for m in self._expiring if m.expiry and start <= m.expiry < end]

    def recent_whale_moves(self, since):
        self._maybe_raise("whales")
        return self._whales

    def open_paper_positions(self, user_id):
        self._maybe_raise("positions")
        return self._positions

    def recent_resolution_alerts(self, since):
        self._maybe_raise("resolution")
        return self._alerts


# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def test_feature_flag_default_true(monkeypatch):
    monkeypatch.delenv("PM_MORNING_BRIEFING_ENABLED", raising=False)
    assert pm_mod.pm_section_enabled() is True


@pytest.mark.parametrize("val", ["0", "false", "False", "no", "off"])
def test_feature_flag_disable(monkeypatch, val):
    monkeypatch.setenv("PM_MORNING_BRIEFING_ENABLED", val)
    assert pm_mod.pm_section_enabled() is False


def test_gather_returns_disabled_when_flag_off(monkeypatch):
    monkeypatch.setenv("PM_MORNING_BRIEFING_ENABLED", "false")
    section = pm_mod.gather_pm_section(FakeDAO())
    assert section.disabled is True
    assert pm_mod.format_pm_section(section) == ""


def test_gather_handles_missing_dao(monkeypatch):
    monkeypatch.setenv("PM_MORNING_BRIEFING_ENABLED", "true")
    section = pm_mod.gather_pm_section(None)
    assert section.error == "dao_unavailable"


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------

def _full_dao():
    today = datetime.now(timezone.utc).date()
    today_noon = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)
    return FakeDAO(
        edges=[
            pm_mod.PMEdge(
                question="Will BTC close above 100k on Friday?",
                category="crypto",
                edge_bps=240,
                fair_price=0.62,
                market_price=0.55,
                venue_market_id="vm-1",
            ),
            pm_mod.PMEdge(
                question="Fed cuts in May?",
                category="macro",
                edge_bps=-180,
                fair_price=0.30,
                market_price=0.42,
            ),
        ],
        expiring=[
            pm_mod.PMExpiring(
                question="Will it rain in NYC today?",
                category="weather",
                expiry=today_noon,
                liquidity_usd=12500,
            ),
        ],
        whales=[
            pm_mod.PMWhaleMove(
                actor="0xabc",
                side="BUY",
                notional_usd=85000,
                question="Election market XYZ",
            ),
        ],
        positions=[
            pm_mod.PMOpenPosition(
                question="Some PM market",
                outcome_token_id="tok-1",
                qty_shares=120,
                avg_entry_price=0.41,
                unrealized_pnl_usd=37.50,
            ),
        ],
        alerts=[
            pm_mod.PMResolutionAlert(
                question="Ambiguous market",
                final_score=0.74,
                tradeable=False,
                rationale="UMA dispute history",
            ),
        ],
    )


def test_format_full_section_contains_all_blocks():
    section = pm_mod.gather_pm_section(_full_dao(), today=datetime.now(timezone.utc).date())
    md = pm_mod.format_pm_section(section)
    assert md.startswith("## Polymarket")
    assert "Top edges" in md
    assert "+240bps" in md
    assert "-180bps" in md
    assert "[crypto]" in md
    assert "Expiring today" in md
    assert "Will it rain in NYC today?" in md
    assert "Whale moves" in md
    assert "0xabc BUY $85.0k" in md
    assert "Open PM paper positions" in md
    assert "120 @ 0.41" in md
    assert "Resolution-risk alerts (F9)" in md
    assert "BLOCKED" in md
    assert "UMA dispute history" in md


def test_format_empty_section_is_empty_string():
    section = pm_mod.gather_pm_section(FakeDAO())
    assert section.is_empty()
    assert pm_mod.format_pm_section(section) == ""


def test_edge_limit_respected():
    edges = [
        pm_mod.PMEdge(question=f"Q{i}", category=None, edge_bps=i * 10, fair_price=0.5, market_price=0.5)
        for i in range(20)
    ]
    section = pm_mod.gather_pm_section(FakeDAO(edges=edges), edge_limit=5)
    assert len(section.edges) == 5


def test_dao_failure_does_not_raise_and_records_error():
    section = pm_mod.gather_pm_section(
        FakeDAO(raise_on={"edges", "positions"}),
    )
    assert section.error is not None
    assert "edges" in section.error
    assert "positions" in section.error
    # Other lanes still produce empty lists, no crash:
    assert section.edges == []
    assert section.open_positions == []


def test_expiring_filter_window():
    today = date(2026, 4, 7)
    in_window = datetime(2026, 4, 7, 14, 0, tzinfo=timezone.utc)
    out_window = datetime(2026, 4, 9, 14, 0, tzinfo=timezone.utc)
    dao = FakeDAO(
        expiring=[
            pm_mod.PMExpiring(question="In", category=None, expiry=in_window, liquidity_usd=None),
            pm_mod.PMExpiring(question="Out", category=None, expiry=out_window, liquidity_usd=None),
        ]
    )
    section = pm_mod.gather_pm_section(dao, today=today)
    questions = [m.question for m in section.expiring]
    assert "In" in questions
    assert "Out" not in questions


def test_section_to_jsonable_round_trips():
    section = pm_mod.gather_pm_section(_full_dao())
    payload = pm_mod._section_to_jsonable(section)
    assert isinstance(payload["markdown"], str)
    assert payload["disabled"] is False
    assert len(payload["edges"]) == 2
    # expiring datetimes are serialised:
    for e in payload["expiring"]:
        assert isinstance(e["expiry"], str) or e["expiry"] is None


def test_partial_marker_appears_when_error_present():
    section = pm_mod.gather_pm_section(
        FakeDAO(
            edges=[
                pm_mod.PMEdge(
                    question="Q", category=None, edge_bps=10,
                    fair_price=0.5, market_price=0.5,
                )
            ],
            raise_on={"whales"},
        )
    )
    md = pm_mod.format_pm_section(section)
    assert "(partial:" in md

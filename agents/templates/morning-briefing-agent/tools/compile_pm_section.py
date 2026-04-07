"""Phase 13 (F12): Polymarket section for the morning briefing.

Builds a "## Polymarket" block that the briefing compiler folds into the
final Haiku prompt and the template fallback. Strictly read-only against
the PM tables; no order side effects.

Sections produced (in order):
  1. Top edges          — top 5 highest-edge candidates from the scanner
  2. Expiring today     — active markets whose expiry is on the briefing date
  3. Whale moves        — best-effort; empty in v1.0 (F8 lands in v1.2)
  4. Open PM positions  — user's open PAPER positions (mode='PAPER')
  5. F9 resolution-risk — recent non-tradeable / high-risk scores

Feature flag: PM_MORNING_BRIEFING_ENABLED (default True). When disabled
the section is empty and no DB calls are made.

The DB collection helper takes a SQLAlchemy-like session whose `.execute`
returns rows with attribute access OR an injected DAO object — whichever
is easier to fake. Unit tests use a fake DAO.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol

# ---------------------------------------------------------------------------
# Feature flag
# ---------------------------------------------------------------------------

def pm_section_enabled() -> bool:
    """Read PM_MORNING_BRIEFING_ENABLED env var. Default True."""
    raw = os.environ.get("PM_MORNING_BRIEFING_ENABLED", "true").strip().lower()
    return raw not in ("0", "false", "no", "off")


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class PMEdge:
    question: str
    category: str | None
    edge_bps: float
    fair_price: float | None
    market_price: float | None
    venue_market_id: str | None = None


@dataclass
class PMExpiring:
    question: str
    category: str | None
    expiry: datetime | None
    liquidity_usd: float | None


@dataclass
class PMWhaleMove:
    actor: str
    side: str
    notional_usd: float
    question: str


@dataclass
class PMOpenPosition:
    question: str
    outcome_token_id: str
    qty_shares: float
    avg_entry_price: float
    unrealized_pnl_usd: float | None


@dataclass
class PMResolutionAlert:
    question: str
    final_score: float | None
    tradeable: bool
    rationale: str | None


@dataclass
class PMSection:
    edges: list[PMEdge] = field(default_factory=list)
    expiring: list[PMExpiring] = field(default_factory=list)
    whales: list[PMWhaleMove] = field(default_factory=list)
    open_positions: list[PMOpenPosition] = field(default_factory=list)
    resolution_alerts: list[PMResolutionAlert] = field(default_factory=list)
    disabled: bool = False
    error: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.edges or self.expiring or self.whales
            or self.open_positions or self.resolution_alerts
        )


# ---------------------------------------------------------------------------
# DAO protocol — anything quacking like this works (real DB or fake)
# ---------------------------------------------------------------------------

class PMSectionDAO(Protocol):
    def top_edges(self, limit: int) -> Iterable[PMEdge]: ...
    def expiring_between(self, start: datetime, end: datetime) -> Iterable[PMExpiring]: ...
    def recent_whale_moves(self, since: datetime) -> Iterable[PMWhaleMove]: ...
    def open_paper_positions(self, user_id: str | None) -> Iterable[PMOpenPosition]: ...
    def recent_resolution_alerts(self, since: datetime) -> Iterable[PMResolutionAlert]: ...


# ---------------------------------------------------------------------------
# Gather (DAO-driven; no hard SQLAlchemy dependency in unit tests)
# ---------------------------------------------------------------------------

def gather_pm_section(
    dao: PMSectionDAO | None,
    *,
    today: date | None = None,
    user_id: str | None = None,
    edge_limit: int = 5,
    lookback_hours: int = 12,
) -> PMSection:
    """Collect everything for the PM block. Pure-ish: never raises."""
    if not pm_section_enabled():
        return PMSection(disabled=True)
    if dao is None:
        return PMSection(error="dao_unavailable")

    today = today or datetime.now(timezone.utc).date()
    day_start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    lookback = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)

    section = PMSection()
    try:
        section.edges = list(dao.top_edges(edge_limit))[:edge_limit]
    except Exception as exc:
        section.error = f"edges:{exc}"
    try:
        section.expiring = list(dao.expiring_between(day_start, day_end))
    except Exception as exc:
        section.error = (section.error or "") + f" expiring:{exc}"
    try:
        section.whales = list(dao.recent_whale_moves(lookback))
    except Exception as exc:
        section.error = (section.error or "") + f" whales:{exc}"
    try:
        section.open_positions = list(dao.open_paper_positions(user_id))
    except Exception as exc:
        section.error = (section.error or "") + f" positions:{exc}"
    try:
        section.resolution_alerts = list(dao.recent_resolution_alerts(lookback))
    except Exception as exc:
        section.error = (section.error or "") + f" resolution:{exc}"

    return section


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "—"
    return f"{x:.0%}" if x <= 1 else f"{x:.2f}"


def _fmt_usd(x: float | None) -> str:
    if x is None:
        return "—"
    if abs(x) >= 1000:
        return f"${x/1000:.1f}k"
    return f"${x:.0f}"


def _fmt_dt(d: datetime | None) -> str:
    if d is None:
        return "—"
    return d.strftime("%H:%MZ")


def format_pm_section(section: PMSection) -> str:
    """Render the PM block as Markdown. Empty string when nothing to say."""
    if section.disabled:
        return ""
    if section.is_empty() and not section.error:
        return ""

    lines: list[str] = ["## Polymarket"]

    # 1. Top edges
    if section.edges:
        lines.append("**Top edges**")
        for e in section.edges[:5]:
            cat = f" [{e.category}]" if e.category else ""
            fair = _fmt_pct(e.fair_price)
            mkt = _fmt_pct(e.market_price)
            lines.append(
                f"- {e.edge_bps:+.0f}bps{cat} {e.question[:80]} "
                f"(fair {fair} vs mkt {mkt})"
            )

    # 2. Expiring today
    if section.expiring:
        lines.append("**Expiring today**")
        for m in section.expiring[:5]:
            cat = f" [{m.category}]" if m.category else ""
            lines.append(
                f"- {_fmt_dt(m.expiry)}{cat} {m.question[:80]} "
                f"(liq {_fmt_usd(m.liquidity_usd)})"
            )

    # 3. Whales
    if section.whales:
        lines.append("**Whale moves**")
        for w in section.whales[:5]:
            lines.append(
                f"- {w.actor} {w.side} {_fmt_usd(w.notional_usd)} on "
                f"{w.question[:60]}"
            )

    # 4. Open paper positions
    if section.open_positions:
        lines.append("**Open PM paper positions**")
        for p in section.open_positions[:10]:
            pnl = _fmt_usd(p.unrealized_pnl_usd) if p.unrealized_pnl_usd is not None else "—"
            lines.append(
                f"- {p.qty_shares:.0f} @ {p.avg_entry_price:.2f} "
                f"({pnl} unrealized) — {p.question[:60]}"
            )

    # 5. F9 resolution-risk alerts
    if section.resolution_alerts:
        lines.append("**Resolution-risk alerts (F9)**")
        for a in section.resolution_alerts[:5]:
            mark = "BLOCKED" if not a.tradeable else "WARN"
            score = f"{a.final_score:.2f}" if a.final_score is not None else "—"
            why = f" — {a.rationale[:80]}" if a.rationale else ""
            lines.append(f"- [{mark} {score}] {a.question[:70]}{why}")

    if section.error:
        lines.append(f"_(partial: {section.error.strip()})_")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI — used by the agent shell to inject the PM block into the events file
# ---------------------------------------------------------------------------

def _build_dao_from_env() -> PMSectionDAO | None:
    """Lazy SQLAlchemy DAO. Returns None when DB is unreachable.

    Kept inside its own helper so unit tests never import SQLAlchemy.
    """
    try:
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session

        from shared.db.models.polymarket import (
            PMMarket,
            PMPosition,
            PMResolutionScore,
        )
    except Exception:
        return None

    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        engine = create_engine(url, future=True)
    except Exception:
        return None

    class _DAO:
        def top_edges(self, limit: int):
            # v1.0: no edge column on pm_markets — leave to live scanner
            # consumer to inject edges via stream:pm:signals. We return [].
            return []

        def expiring_between(self, start, end):
            with Session(engine) as s:
                stmt = (
                    select(PMMarket)
                    .where(PMMarket.is_active.is_(True))
                    .where(PMMarket.expiry.is_not(None))
                    .where(PMMarket.expiry >= start)
                    .where(PMMarket.expiry < end)
                    .limit(20)
                )
                rows = s.execute(stmt).scalars().all()
            return [
                PMExpiring(
                    question=r.question,
                    category=r.category,
                    expiry=r.expiry,
                    liquidity_usd=r.liquidity_usd,
                )
                for r in rows
            ]

        def recent_whale_moves(self, since):
            return []  # F8 lands in v1.2

        def open_paper_positions(self, user_id):
            with Session(engine) as s:
                stmt = (
                    select(PMPosition, PMMarket)
                    .join(PMMarket, PMPosition.pm_market_id == PMMarket.id)
                    .where(PMPosition.mode == "PAPER")
                    .where(PMPosition.closed_at.is_(None))
                    .limit(20)
                )
                rows = s.execute(stmt).all()
            return [
                PMOpenPosition(
                    question=mkt.question,
                    outcome_token_id=pos.outcome_token_id,
                    qty_shares=pos.qty_shares,
                    avg_entry_price=pos.avg_entry_price,
                    unrealized_pnl_usd=pos.unrealized_pnl_usd,
                )
                for pos, mkt in rows
            ]

        def recent_resolution_alerts(self, since):
            with Session(engine) as s:
                stmt = (
                    select(PMResolutionScore, PMMarket)
                    .join(PMMarket, PMResolutionScore.pm_market_id == PMMarket.id)
                    .where(PMResolutionScore.scored_at >= since)
                    .where(
                        (PMResolutionScore.tradeable.is_(False))
                        | (PMResolutionScore.final_score >= 0.5)
                    )
                    .limit(10)
                )
                rows = s.execute(stmt).all()
            return [
                PMResolutionAlert(
                    question=mkt.question,
                    final_score=score.final_score,
                    tradeable=score.tradeable,
                    rationale=score.llm_rationale,
                )
                for score, mkt in rows
            ]

    return _DAO()


def _section_to_jsonable(section: PMSection) -> dict[str, Any]:
    return {
        "disabled": section.disabled,
        "error": section.error,
        "edges": [e.__dict__ for e in section.edges],
        "expiring": [
            {**m.__dict__, "expiry": m.expiry.isoformat() if m.expiry else None}
            for m in section.expiring
        ],
        "whales": [w.__dict__ for w in section.whales],
        "open_positions": [p.__dict__ for p in section.open_positions],
        "resolution_alerts": [a.__dict__ for a in section.resolution_alerts],
        "markdown": format_pm_section(section),
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--events", required=True, help="Path to overnight_events.json (in/out)")
    p.add_argument("--user-id", default=None)
    p.add_argument("--edge-limit", type=int, default=5)
    args = p.parse_args()

    events_path = Path(args.events)
    if not events_path.exists():
        print(f"[pm_section] {events_path} not found", file=sys.stderr)
        sys.exit(1)

    bundle = json.loads(events_path.read_text())

    if not pm_section_enabled():
        bundle["pm_section"] = {"disabled": True, "markdown": ""}
    else:
        dao = _build_dao_from_env()
        section = gather_pm_section(dao, user_id=args.user_id, edge_limit=args.edge_limit)
        bundle["pm_section"] = _section_to_jsonable(section)

    events_path.write_text(json.dumps(bundle, indent=2, default=str))
    md_len = len(bundle["pm_section"].get("markdown") or "")
    print(f"[pm_section] wrote pm_section ({md_len} chars) into {events_path}")


if __name__ == "__main__":
    main()

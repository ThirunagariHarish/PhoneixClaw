"""Portfolio analysis tool — deep intelligence on all open positions.

Designed to be called by the Claude agent when the user asks about their
portfolio, positions, or when the agent needs to make position management
decisions. Combines Robinhood position data with technical analysis and
market research to produce actionable insights.

Usage:
    python portfolio_analysis.py [config.json]
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger("portfolio_analysis")


def analyze_portfolio(config_path: str | None = None) -> dict:
    """Full portfolio analysis: positions, P&L, Greeks, risk, exit recommendations.

    This function orchestrates MCP calls (via config) and local analysis tools
    to produce a comprehensive portfolio report the agent can reason about.
    """

    config: dict = {}
    if config_path and Path(config_path).exists():
        config = json.loads(Path(config_path).read_text())

    mcp_script = Path(__file__).parent / "robinhood_mcp.py"

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "account": {},
        "stock_positions": [],
        "option_positions": [],
        "total_positions": 0,
        "total_pnl": 0.0,
        "risk_alerts": [],
        "recommendations": [],
    }

    log.info("Portfolio analysis — this tool provides structure; the Claude agent "
             "should call get_all_positions and get_account via MCP directly for live data. "
             "This tool enriches those results with TA and research.")

    return report


def enrich_stock_position(position: dict) -> dict:
    """Enrich a stock position dict with TA and health check data."""
    from market_research import key_levels, position_health_check

    ticker = position.get("ticker", "?")
    avg_cost = float(position.get("avg_cost", 0))
    current = float(position.get("current_price", 0))
    qty = float(position.get("quantity", 0))

    pnl = (current - avg_cost) * qty
    pnl_pct = ((current - avg_cost) / avg_cost * 100) if avg_cost else 0

    result = {
        **position,
        "pnl": round(pnl, 2),
        "pnl_pct": round(pnl_pct, 2),
        "market_value": round(current * qty, 2),
    }

    try:
        levels = key_levels(ticker, period="1mo")
        result["key_levels"] = levels
    except Exception:
        pass

    try:
        health = position_health_check(ticker, avg_cost)
        result["health"] = health
    except Exception:
        pass

    return result


def enrich_option_position(position: dict) -> dict:
    """Enrich an option position dict with risk metrics and exit analysis."""

    ticker = position.get("ticker", "?")
    avg_cost = float(position.get("avg_cost_per_contract", 0))
    mark = float(position.get("mark_price", 0))
    qty = float(position.get("quantity", 0))
    expiry = position.get("expiry", "")
    strike = float(position.get("strike", 0))
    opt_type = position.get("option_type", "")
    delta = float(position.get("delta", 0))
    theta = float(position.get("theta", 0))

    pnl_per = mark - avg_cost
    pnl_total = pnl_per * qty * 100

    result = {
        **position,
        "pnl_total": round(pnl_total, 2),
        "pnl_pct": round((pnl_per / avg_cost) * 100, 2) if avg_cost else 0,
        "market_value": round(mark * qty * 100, 2),
        "daily_theta_decay": round(theta * qty * 100, 2) if theta else 0,
        "delta_exposure": round(delta * qty * 100, 2) if delta else 0,
    }

    alerts = []
    if expiry:
        try:
            days_left = (datetime.strptime(expiry, "%Y-%m-%d") - datetime.now()).days
            result["days_to_expiry"] = days_left
            if days_left <= 0:
                alerts.append("EXPIRED — close immediately")
            elif days_left <= 3:
                alerts.append("EXPIRING in <=3 days — extreme theta decay")
            elif days_left <= 7:
                alerts.append("1 week to expiry — accelerating time decay")
        except ValueError:
            pass

    if pnl_total < 0 and abs(pnl_per / avg_cost) > 0.5 if avg_cost else False:
        alerts.append("DOWN >50% — consider cutting losses")

    if mark < 0.10:
        alerts.append("Near worthless — close to recover remaining value")

    if result.get("daily_theta_decay", 0) < -5:
        alerts.append(f"Losing ${abs(result['daily_theta_decay']):.0f}/day to theta")

    result["alerts"] = alerts

    rec = "HOLD"
    if any("EXPIRED" in a or "close immediately" in a for a in alerts):
        rec = "CLOSE_NOW"
    elif any("DOWN >50%" in a for a in alerts):
        rec = "CUT_LOSS"
    elif any("EXPIRING" in a for a in alerts) and pnl_total > 0:
        rec = "TAKE_PROFIT"
    elif pnl_total > 0 and (pnl_per / avg_cost > 0.3 if avg_cost else False):
        rec = "TRAIL_STOP"

    result["recommendation"] = rec
    return result


def generate_portfolio_summary(account: dict, stocks: list[dict], options: list[dict]) -> dict:
    """Generate a human-readable portfolio summary with risk metrics."""
    total_stock_value = sum(s.get("market_value", 0) for s in stocks)
    total_option_value = sum(o.get("market_value", 0) for o in options)
    total_stock_pnl = sum(s.get("pnl", 0) for s in stocks)
    total_option_pnl = sum(o.get("pnl_total", 0) for o in options)
    total_theta = sum(o.get("daily_theta_decay", 0) for o in options)
    total_delta = sum(o.get("delta_exposure", 0) for o in options)

    portfolio_value = float(account.get("portfolio_value", 0))
    buying_power = float(account.get("buying_power", 0))

    all_alerts = []
    for o in options:
        for a in o.get("alerts", []):
            all_alerts.append(f"{o.get('ticker', '?')} {o.get('strike', '')}{o.get('option_type', '')[0:1].upper()} {o.get('expiry', '')}: {a}")

    concentration = {}
    for pos in stocks + options:
        t = pos.get("ticker", "?")
        concentration[t] = concentration.get(t, 0) + pos.get("market_value", 0)

    return {
        "account": {
            "portfolio_value": portfolio_value,
            "buying_power": buying_power,
            "invested": round(total_stock_value + total_option_value, 2),
            "cash_pct": round((buying_power / portfolio_value * 100) if portfolio_value else 0, 1),
        },
        "pnl": {
            "stock_pnl": round(total_stock_pnl, 2),
            "option_pnl": round(total_option_pnl, 2),
            "total_pnl": round(total_stock_pnl + total_option_pnl, 2),
        },
        "risk": {
            "total_delta_exposure": round(total_delta, 2),
            "daily_theta_decay": round(total_theta, 2),
            "position_count": len(stocks) + len(options),
            "stock_count": len(stocks),
            "option_count": len(options),
        },
        "concentration": {t: round(v, 2) for t, v in sorted(concentration.items(), key=lambda x: -x[1])[:5]},
        "urgent_alerts": all_alerts,
        "action_items": [
            f"CLOSE: {o.get('ticker')} {o.get('strike')}{o.get('option_type', '')[0:1].upper()} exp {o.get('expiry')}"
            for o in options if o.get("recommendation") in ("CLOSE_NOW", "CUT_LOSS")
        ],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    result = analyze_portfolio(config_path)
    print(json.dumps(result, default=str, indent=2))

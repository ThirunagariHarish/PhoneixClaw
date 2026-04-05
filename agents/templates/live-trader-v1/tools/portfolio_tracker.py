"""Portfolio tracker: manage open positions, P&L, and trade history.

Usage:
    python portfolio_tracker.py --action summary --config config.json
    python portfolio_tracker.py --action add --ticker SPX --side buy --price 12.5 --quantity 10
    python portfolio_tracker.py --action close --trade-id <id> --exit-price 15.0
    python portfolio_tracker.py --action partial_close --trade-id <id> --exit-price 15.0 --close-quantity 5
    python portfolio_tracker.py --action update_prices
"""

import argparse
import json
import logging
import sys
import uuid
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")

try:
    import yfinance as yf
except ImportError:
    yf = None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [portfolio] %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)

DEFAULT_PORTFOLIO_PATH = "portfolio.json"

EMPTY_PORTFOLIO = {
    "positions": [],
    "closed_trades": [],
    "daily_pnl": [],
    "metadata": {
        "created": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_trades": 0,
        "total_realized_pnl": 0.0,
    },
}


# ---------------------------------------------------------------------------
# Portfolio I/O
# ---------------------------------------------------------------------------

def load_portfolio(path: str = DEFAULT_PORTFOLIO_PATH) -> dict:
    p = Path(path)
    if p.exists():
        try:
            data = json.loads(p.read_text())
            for key in EMPTY_PORTFOLIO:
                if key not in data:
                    data[key] = EMPTY_PORTFOLIO[key] if not isinstance(EMPTY_PORTFOLIO[key], dict) else dict(EMPTY_PORTFOLIO[key])
            return data
        except (json.JSONDecodeError, KeyError) as exc:
            log.warning("Corrupt portfolio file, starting fresh: %s", exc)
    return json.loads(json.dumps(EMPTY_PORTFOLIO))


def save_portfolio(portfolio: dict, path: str = DEFAULT_PORTFOLIO_PATH) -> None:
    portfolio["metadata"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    Path(path).write_text(json.dumps(portfolio, indent=2, default=str))
    log.info("Portfolio saved to %s", path)


# ---------------------------------------------------------------------------
# Position management
# ---------------------------------------------------------------------------

def add_position(portfolio: dict, ticker: str, side: str, price: float,
                 quantity: int, option_type: str | None = None,
                 strike: float | None = None, expiry: str | None = None,
                 notes: str = "") -> dict:
    """Add a new position to the portfolio."""
    trade_id = str(uuid.uuid4())[:8]
    position = {
        "trade_id": trade_id,
        "ticker": ticker.upper(),
        "side": side.lower(),
        "entry_price": price,
        "current_price": price,
        "quantity": quantity,
        "remaining_quantity": quantity,
        "entry_time": datetime.now(timezone.utc).isoformat(),
        "unrealized_pnl": 0.0,
        "unrealized_pnl_pct": 0.0,
        "status": "open",
        "notes": notes,
    }

    if option_type:
        position["option_type"] = option_type
        position["strike"] = strike
        position["expiry"] = expiry

    portfolio["positions"].append(position)
    portfolio["metadata"]["total_trades"] += 1
    log.info("Added position: %s %s %s @ %.2f x %d [%s]",
             side, ticker, option_type or "equity", price, quantity, trade_id)

    return {"action": "add", "trade_id": trade_id, "position": position}


def close_position(portfolio: dict, trade_id: str, exit_price: float,
                   notes: str = "") -> dict:
    """Close an entire position."""
    for i, pos in enumerate(portfolio["positions"]):
        if pos["trade_id"] == trade_id and pos["status"] == "open":
            multiplier = 1 if pos["side"] == "buy" else -1
            pnl = multiplier * (exit_price - pos["entry_price"]) * pos["remaining_quantity"]
            pnl_pct = multiplier * (exit_price - pos["entry_price"]) / pos["entry_price"] * 100

            closed_trade = {
                **pos,
                "exit_price": exit_price,
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "realized_pnl": round(pnl, 2),
                "realized_pnl_pct": round(pnl_pct, 2),
                "closed_quantity": pos["remaining_quantity"],
                "status": "closed",
                "close_notes": notes,
            }

            portfolio["closed_trades"].append(closed_trade)
            portfolio["positions"].pop(i)
            portfolio["metadata"]["total_realized_pnl"] = round(
                portfolio["metadata"]["total_realized_pnl"] + pnl, 2
            )

            _update_daily_pnl(portfolio, pnl)
            log.info("Closed position %s: PnL=%.2f (%.2f%%)", trade_id, pnl, pnl_pct)
            return {"action": "close", "trade_id": trade_id, "realized_pnl": round(pnl, 2),
                    "realized_pnl_pct": round(pnl_pct, 2)}

    return {"action": "close", "error": f"Position {trade_id} not found or already closed"}


def partial_close(portfolio: dict, trade_id: str, exit_price: float,
                  close_quantity: int, notes: str = "") -> dict:
    """Partially close a position."""
    for pos in portfolio["positions"]:
        if pos["trade_id"] == trade_id and pos["status"] == "open":
            if close_quantity > pos["remaining_quantity"]:
                return {"action": "partial_close", "error":
                        f"Cannot close {close_quantity}, only {pos['remaining_quantity']} remaining"}
            if close_quantity <= 0:
                return {"action": "partial_close", "error": "close_quantity must be positive"}

            multiplier = 1 if pos["side"] == "buy" else -1
            pnl = multiplier * (exit_price - pos["entry_price"]) * close_quantity
            pnl_pct = multiplier * (exit_price - pos["entry_price"]) / pos["entry_price"] * 100

            pos["remaining_quantity"] -= close_quantity
            remaining = pos["remaining_quantity"]

            partial_record = {
                "trade_id": trade_id,
                "ticker": pos["ticker"],
                "side": pos["side"],
                "entry_price": pos["entry_price"],
                "exit_price": exit_price,
                "closed_quantity": close_quantity,
                "exit_time": datetime.now(timezone.utc).isoformat(),
                "realized_pnl": round(pnl, 2),
                "realized_pnl_pct": round(pnl_pct, 2),
                "status": "partial_close",
                "close_notes": notes,
            }
            portfolio["closed_trades"].append(partial_record)
            portfolio["metadata"]["total_realized_pnl"] = round(
                portfolio["metadata"]["total_realized_pnl"] + pnl, 2
            )

            if remaining == 0:
                pos["status"] = "closed"
                portfolio["positions"] = [p for p in portfolio["positions"] if p["status"] == "open"]

            _update_daily_pnl(portfolio, pnl)
            log.info("Partial close %s: %d @ %.2f, PnL=%.2f, remaining=%d",
                     trade_id, close_quantity, exit_price, pnl, remaining)
            return {"action": "partial_close", "trade_id": trade_id,
                    "closed_quantity": close_quantity, "remaining": remaining,
                    "realized_pnl": round(pnl, 2), "realized_pnl_pct": round(pnl_pct, 2)}

    return {"action": "partial_close", "error": f"Position {trade_id} not found or already closed"}


def update_prices(portfolio: dict) -> dict:
    """Fetch current prices for all open positions and update unrealized P&L."""
    if yf is None:
        return {"action": "update_prices", "error": "yfinance not installed"}

    updated = 0
    total_unrealized = 0.0

    ticker_map = {"SPX": "^GSPC", "NDX": "^NDX", "DJI": "^DJI", "VIX": "^VIX", "RUT": "^RUT"}

    tickers = list(set(pos["ticker"] for pos in portfolio["positions"] if pos["status"] == "open"))
    yf_tickers = [ticker_map.get(t, t) for t in tickers]

    prices = {}
    for orig, yft in zip(tickers, yf_tickers):
        try:
            data = yf.download(yft, period="1d", interval="1m", progress=False)
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
            if not data.empty:
                prices[orig] = float(data["Close"].iloc[-1])
        except Exception as exc:
            log.warning("Price fetch failed for %s: %s", yft, exc)

    for pos in portfolio["positions"]:
        if pos["status"] != "open":
            continue
        ticker = pos["ticker"]
        if ticker in prices:
            pos["current_price"] = round(prices[ticker], 2)
            multiplier = 1 if pos["side"] == "buy" else -1
            pnl = multiplier * (pos["current_price"] - pos["entry_price"]) * pos["remaining_quantity"]
            pnl_pct = multiplier * (pos["current_price"] - pos["entry_price"]) / pos["entry_price"] * 100
            pos["unrealized_pnl"] = round(pnl, 2)
            pos["unrealized_pnl_pct"] = round(pnl_pct, 2)
            total_unrealized += pnl
            updated += 1

    log.info("Updated %d/%d positions, total unrealized: %.2f", updated, len(tickers), total_unrealized)
    return {"action": "update_prices", "updated": updated, "total_unrealized_pnl": round(total_unrealized, 2)}


def get_summary(portfolio: dict) -> dict:
    """Generate a full portfolio summary."""
    open_positions = [p for p in portfolio["positions"] if p["status"] == "open"]

    total_unrealized = sum(p.get("unrealized_pnl", 0) for p in open_positions)
    total_realized = portfolio["metadata"].get("total_realized_pnl", 0)
    total_invested = sum(p["entry_price"] * p["remaining_quantity"] for p in open_positions)

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily_entries = [d for d in portfolio.get("daily_pnl", []) if d.get("date") == today_str]
    daily_realized = sum(d.get("pnl", 0) for d in daily_entries)

    wins = [t for t in portfolio["closed_trades"] if t.get("realized_pnl", 0) > 0]
    losses = [t for t in portfolio["closed_trades"] if t.get("realized_pnl", 0) < 0]
    total_closed = len(portfolio["closed_trades"])
    win_rate = len(wins) / total_closed if total_closed > 0 else 0

    avg_win = np.mean([t["realized_pnl"] for t in wins]) if wins else 0
    avg_loss = np.mean([abs(t["realized_pnl"]) for t in losses]) if losses else 0
    profit_factor = (sum(t["realized_pnl"] for t in wins) /
                     abs(sum(t["realized_pnl"] for t in losses))) if losses else float("inf")

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "open_positions": len(open_positions),
        "positions": open_positions,
        "total_invested": round(total_invested, 2),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_realized_pnl": round(total_realized, 2),
        "total_pnl": round(total_realized + total_unrealized, 2),
        "daily_realized_pnl": round(daily_realized, 2),
        "daily_pnl_pct": round(daily_realized / total_invested * 100, 2) if total_invested > 0 else 0,
        "stats": {
            "total_trades": portfolio["metadata"].get("total_trades", 0),
            "closed_trades": total_closed,
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": round(win_rate, 3),
            "avg_win": round(float(avg_win), 2),
            "avg_loss": round(float(avg_loss), 2),
            "profit_factor": round(profit_factor, 2) if profit_factor != float("inf") else None,
            "largest_win": round(max((t["realized_pnl"] for t in wins), default=0), 2),
            "largest_loss": round(min((t["realized_pnl"] for t in losses), default=0), 2),
        },
        "recent_trades": portfolio["closed_trades"][-10:],
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _update_daily_pnl(portfolio: dict, pnl: float) -> None:
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    daily = portfolio.setdefault("daily_pnl", [])
    for entry in daily:
        if entry.get("date") == today_str:
            entry["pnl"] = round(entry["pnl"] + pnl, 2)
            entry["trades"] = entry.get("trades", 0) + 1
            return
    daily.append({"date": today_str, "pnl": round(pnl, 2), "trades": 1})


# ---------------------------------------------------------------------------
# Compatibility shim: allow update_prices to work even without pandas at top level
# ---------------------------------------------------------------------------
try:
    import pandas as pd
except ImportError:
    pd = None


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.floating, np.float64, np.float32)):
        return None if np.isnan(obj) else round(float(obj), 6)
    if isinstance(obj, (np.integer, np.int64)):
        return int(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


def main():
    parser = argparse.ArgumentParser(description="Portfolio position and P&L tracker")
    parser.add_argument("--action", required=True,
                        choices=["add", "close", "partial_close", "update_prices", "summary"],
                        help="Action to perform")
    parser.add_argument("--portfolio", default=DEFAULT_PORTFOLIO_PATH, help="Portfolio JSON path")
    parser.add_argument("--config", default=None, help="Config JSON (optional)")

    # add args
    parser.add_argument("--ticker", default=None, help="Ticker symbol")
    parser.add_argument("--side", default=None, choices=["buy", "sell"], help="Trade side")
    parser.add_argument("--price", type=float, default=None, help="Entry/exit price")
    parser.add_argument("--quantity", type=int, default=None, help="Quantity")
    parser.add_argument("--option-type", default=None, choices=["call", "put"], help="Option type")
    parser.add_argument("--strike", type=float, default=None, help="Option strike")
    parser.add_argument("--expiry", default=None, help="Option expiry YYYY-MM-DD")
    parser.add_argument("--notes", default="", help="Trade notes")

    # close args
    parser.add_argument("--trade-id", default=None, help="Trade ID to close")
    parser.add_argument("--exit-price", type=float, default=None, help="Exit price")
    parser.add_argument("--close-quantity", type=int, default=None, help="Quantity to close (partial)")

    parser.add_argument("--output", default=None, help="Output JSON (for summary)")
    args = parser.parse_args()

    portfolio = load_portfolio(args.portfolio)

    if args.action == "add":
        if not all([args.ticker, args.side, args.price, args.quantity]):
            log.error("add requires --ticker, --side, --price, --quantity")
            sys.exit(1)
        result = add_position(portfolio, args.ticker, args.side, args.price, args.quantity,
                              option_type=args.option_type, strike=args.strike,
                              expiry=args.expiry, notes=args.notes)

    elif args.action == "close":
        if not all([args.trade_id, args.exit_price]):
            log.error("close requires --trade-id, --exit-price")
            sys.exit(1)
        result = close_position(portfolio, args.trade_id, args.exit_price, notes=args.notes)

    elif args.action == "partial_close":
        if not all([args.trade_id, args.exit_price, args.close_quantity]):
            log.error("partial_close requires --trade-id, --exit-price, --close-quantity")
            sys.exit(1)
        result = partial_close(portfolio, args.trade_id, args.exit_price,
                               args.close_quantity, notes=args.notes)

    elif args.action == "update_prices":
        result = update_prices(portfolio)

    elif args.action == "summary":
        result = get_summary(portfolio)

    else:
        log.error("Unknown action: %s", args.action)
        sys.exit(1)

    save_portfolio(portfolio, args.portfolio)

    result = _json_safe(result)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2, default=str)

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

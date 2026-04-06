"""Paper portfolio tracker for paper trading mode.

Periodically fetches current prices for all watchlist tickers and computes
simulated P&L vs the entry price recorded when each ticker was added. POSTs
updates to Phoenix API for the dashboard.

Usage:
    # Update all open paper positions (run periodically, e.g. every 5 min)
    python paper_portfolio.py --update --config config.json

    # Get summary
    python paper_portfolio.py --summary --config config.json

    # Add a paper position
    python paper_portfolio.py --add --ticker AAPL --side buy --price 185.50 \\
        --reasoning "Bullish breakout signal"

    # Close a paper position
    python paper_portfolio.py --close --ticker AAPL --reason "Exit signal"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PAPER_FILE = Path("paper_trades.json")


def _load_trades() -> list[dict]:
    if PAPER_FILE.exists():
        try:
            return json.loads(PAPER_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return []
    return []


def _save_trades(trades: list[dict]) -> None:
    PAPER_FILE.write_text(json.dumps(trades, indent=2, default=str))


def _get_api_config() -> dict:
    cfg_path = Path("config.json")
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text())
            return {
                "url": cfg.get("phoenix_api_url") or os.getenv("PHOENIX_API_URL", ""),
                "key": cfg.get("phoenix_api_key", ""),
                "agent_id": cfg.get("agent_id", ""),
            }
        except Exception:
            pass
    return {"url": os.getenv("PHOENIX_API_URL", ""), "key": "", "agent_id": ""}


def add_paper_position(ticker: str, side: str, price: float,
                       quantity: int = 1, signal_data: dict | None = None) -> dict:
    """Record a new paper position and add to Robinhood watchlist."""
    trades = _load_trades()

    entry = {
        "id": f"paper_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{len(trades)}",
        "ticker": ticker,
        "side": side,
        "entry_price": price,
        "current_price": price,
        "quantity": quantity,
        "simulated_pnl": 0.0,
        "simulated_pnl_pct": 0.0,
        "signal_data": signal_data or {},
        "status": "open",
        "opened_at": datetime.now(timezone.utc).isoformat(),
        "closed_at": None,
        "close_reason": None,
    }
    trades.append(entry)
    _save_trades(trades)

    # Add to Robinhood watchlist via MCP (best-effort)
    _add_to_robinhood(ticker)

    # Report to Phoenix API
    _report_to_phoenix("add", entry)

    return {"status": "added", "id": entry["id"], "ticker": ticker}


def update_positions() -> dict:
    """Fetch current prices and update simulated P&L for all open paper positions."""
    trades = _load_trades()
    open_trades = [t for t in trades if t.get("status") == "open"]
    if not open_trades:
        return {"updated": 0, "message": "No open paper positions"}

    tickers = list({t["ticker"] for t in open_trades})
    prices = _fetch_prices(tickers)

    updated = 0
    for trade in open_trades:
        ticker = trade["ticker"]
        if ticker not in prices:
            continue
        current = prices[ticker]
        entry = trade["entry_price"]
        side = trade.get("side", "buy")
        qty = trade.get("quantity", 1)

        if side == "buy":
            pnl = (current - entry) * qty
            pnl_pct = (current - entry) / entry * 100 if entry > 0 else 0
        else:
            pnl = (entry - current) * qty
            pnl_pct = (entry - current) / entry * 100 if entry > 0 else 0

        trade["current_price"] = current
        trade["simulated_pnl"] = round(pnl, 2)
        trade["simulated_pnl_pct"] = round(pnl_pct, 2)
        trade["last_price_update"] = datetime.now(timezone.utc).isoformat()
        updated += 1

    _save_trades(trades)
    _report_to_phoenix("update", {"updated": updated, "trades": open_trades})
    return {"updated": updated, "open_positions": len(open_trades)}


def close_paper_position(ticker: str, reason: str = "Manual close") -> dict:
    """Close an open paper position and compute realized P&L."""
    trades = _load_trades()
    prices = _fetch_prices([ticker])
    exit_price = prices.get(ticker)

    for trade in trades:
        if trade["ticker"] == ticker and trade["status"] == "open":
            if exit_price is None:
                exit_price = trade.get("current_price", trade["entry_price"])

            entry = trade["entry_price"]
            side = trade.get("side", "buy")
            qty = trade.get("quantity", 1)

            if side == "buy":
                pnl = (exit_price - entry) * qty
                pnl_pct = (exit_price - entry) / entry * 100 if entry > 0 else 0
            else:
                pnl = (entry - exit_price) * qty
                pnl_pct = (entry - exit_price) / entry * 100 if entry > 0 else 0

            trade["status"] = "closed"
            trade["current_price"] = exit_price
            trade["simulated_pnl"] = round(pnl, 2)
            trade["simulated_pnl_pct"] = round(pnl_pct, 2)
            trade["closed_at"] = datetime.now(timezone.utc).isoformat()
            trade["close_reason"] = reason

            _save_trades(trades)
            _remove_from_robinhood(ticker)
            _report_to_phoenix("close", trade)
            return {
                "status": "closed",
                "ticker": ticker,
                "entry_price": entry,
                "exit_price": exit_price,
                "simulated_pnl": trade["simulated_pnl"],
                "pnl_pct": trade["simulated_pnl_pct"],
            }

    return {"status": "not_found", "ticker": ticker}


def get_summary() -> dict:
    """Return aggregate paper portfolio summary."""
    trades = _load_trades()
    open_trades = [t for t in trades if t.get("status") == "open"]
    closed_trades = [t for t in trades if t.get("status") == "closed"]

    total_unrealized = sum(t.get("simulated_pnl", 0) for t in open_trades)
    total_realized = sum(t.get("simulated_pnl", 0) for t in closed_trades)
    wins = sum(1 for t in closed_trades if t.get("simulated_pnl", 0) > 0)

    return {
        "open_positions": len(open_trades),
        "closed_positions": len(closed_trades),
        "total_unrealized_pnl": round(total_unrealized, 2),
        "total_realized_pnl": round(total_realized, 2),
        "win_rate": round(wins / len(closed_trades), 3) if closed_trades else 0.0,
        "open_tickers": [t["ticker"] for t in open_trades],
    }


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """Fetch current prices via yfinance."""
    prices: dict[str, float] = {}
    try:
        import yfinance as yf
        if len(tickers) == 1:
            data = yf.download(tickers[0], period="1d", progress=False)
            if not data.empty:
                if hasattr(data.columns, "levels"):
                    data.columns = data.columns.get_level_values(0)
                prices[tickers[0]] = float(data["Close"].iloc[-1])
        else:
            data = yf.download(tickers, period="1d", progress=False, group_by="ticker")
            for tk in tickers:
                try:
                    if tk in data.columns.get_level_values(0):
                        prices[tk] = float(data[tk]["Close"].iloc[-1])
                except (KeyError, IndexError):
                    pass
    except Exception:
        pass
    return prices


def _add_to_robinhood(ticker: str) -> None:
    """Best-effort add to Robinhood watchlist via subprocess to MCP."""
    try:
        import subprocess
        tools_dir = Path(__file__).resolve().parent
        # Direct call to a CLI mode if available, or send JSON-RPC stdin
        # For now, use a simple environment-based call to robin_stocks if installed
        env = os.environ.copy()
        try:
            import robin_stocks.robinhood as r
            if env.get("RH_USERNAME") and env.get("RH_PASSWORD"):
                # Login is best-effort; may already be logged in
                try:
                    r.login(env["RH_USERNAME"], env["RH_PASSWORD"],
                            mfa_code=None, store_session=True)
                except Exception:
                    pass
                r.account.post_symbols_to_watchlist([ticker], "Phoenix Paper")
        except ImportError:
            pass
    except Exception as e:
        print(f"  [paper_portfolio] add_to_watchlist failed: {e}", file=sys.stderr)


def _remove_from_robinhood(ticker: str) -> None:
    try:
        import robin_stocks.robinhood as r
        if os.environ.get("RH_USERNAME"):
            r.account.delete_symbols_from_watchlist([ticker], "Phoenix Paper")
    except Exception:
        pass


def _report_to_phoenix(event: str, data: dict) -> None:
    """Report paper trade event to Phoenix API (non-blocking)."""
    try:
        from report_to_phoenix import report_progress
        if event == "add":
            report_progress("paper_trade_add",
                            f"Paper {data.get('side', '?').upper()} {data.get('ticker', '?')} @ ${data.get('entry_price', 0)}",
                            -1, {"paper_trade": data, "decision_status": "paper"})
        elif event == "close":
            report_progress("paper_trade_close",
                            f"Paper closed {data.get('ticker', '?')} — P&L: ${data.get('simulated_pnl', 0)}",
                            -1, {"paper_trade": data, "decision_status": "paper"})
        elif event == "update":
            report_progress("paper_portfolio_update",
                            f"Updated {data.get('updated', 0)} paper positions", -1, data)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Paper portfolio tracker")
    parser.add_argument("--add", action="store_true", help="Add a paper position")
    parser.add_argument("--update", action="store_true", help="Update all positions")
    parser.add_argument("--close", action="store_true", help="Close a position")
    parser.add_argument("--summary", action="store_true", help="Show summary")
    parser.add_argument("--ticker", help="Ticker symbol")
    parser.add_argument("--side", default="buy")
    parser.add_argument("--price", type=float)
    parser.add_argument("--quantity", type=int, default=1)
    parser.add_argument("--reason", default="Manual")
    parser.add_argument("--reasoning", default="")
    parser.add_argument("--config", default="config.json")
    args = parser.parse_args()

    if args.add:
        if not args.ticker or args.price is None:
            print("Error: --ticker and --price required", file=sys.stderr)
            sys.exit(1)
        result = add_paper_position(args.ticker, args.side, args.price,
                                     args.quantity, {"reasoning": args.reasoning})
    elif args.update:
        result = update_positions()
    elif args.close:
        if not args.ticker:
            print("Error: --ticker required", file=sys.stderr)
            sys.exit(1)
        result = close_paper_position(args.ticker, args.reason)
    elif args.summary:
        result = get_summary()
    else:
        parser.print_help()
        return

    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

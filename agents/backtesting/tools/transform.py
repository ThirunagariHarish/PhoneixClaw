"""Transformation pipeline: Discord messages → clean trade rows.

Usage:
    python tools/transform.py --config config.json --output output/transformed.parquet
"""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import pandas as pd


# ── Signal Parsing ──────────────────────────────────────────────────────────

TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b|(?<!\w)([A-Z]{2,5})(?:\s+\d+[cp]|\s+(?:calls?|puts?))", re.IGNORECASE)
PRICE_RE = re.compile(r"(?:@|at|entry|price|for)\s*\$?([\d]+(?:\.\d+)?)", re.IGNORECASE)
OPTION_RE = re.compile(r"(\d{1,2}/\d{1,2}(?:/\d{2,4})?)\s*(\d+(?:\.\d+)?)\s*([cpCP])", re.IGNORECASE)
BUY_WORDS = re.compile(r"\b(buy|bought|long|entered|taking|grabbed|added|opening)\b", re.IGNORECASE)
SELL_WORDS = re.compile(r"\b(sell|sold|closing|closed|exited|trimmed?|trim|profit|out)\b", re.IGNORECASE)
PCT_RE = re.compile(r"(\d+)\s*%", re.IGNORECASE)
TARGET_RE = re.compile(r"(?:target|tp|take.?profit)\s*\$?([\d]+(?:\.\d+)?)", re.IGNORECASE)
STOP_RE = re.compile(r"(?:stop|sl|stop.?loss)\s*\$?([\d]+(?:\.\d+)?)", re.IGNORECASE)

KNOWN_TICKERS = {"SPX", "SPY", "QQQ", "AAPL", "TSLA", "AMZN", "GOOGL", "MSFT", "NVDA", "META",
                  "AMD", "NFLX", "BA", "DIS", "JPM", "GS", "V", "MA", "WMT", "HD",
                  "COST", "NKE", "PYPL", "SQ", "SHOP", "COIN", "PLTR", "SOFI", "HOOD",
                  "IWM", "DIA", "XLF", "XLE", "XLK", "GLD", "SLV", "TLT", "VIX",
                  "SPXW", "NDX", "NDXP", "RUT"}


def parse_signal(content: str, posted_at: datetime) -> Optional[dict]:
    """Parse a Discord message into a trade signal."""
    content_upper = content.upper()

    # Extract tickers
    tickers = set()
    for m in TICKER_RE.finditer(content):
        t = (m.group(1) or m.group(2) or "").upper()
        if t and len(t) >= 2:
            tickers.add(t)

    if not tickers:
        return None

    ticker = sorted(tickers, key=lambda t: (t not in KNOWN_TICKERS, t))[0]

    # Signal type
    has_buy = bool(BUY_WORDS.search(content))
    has_sell = bool(SELL_WORDS.search(content))

    if has_buy and not has_sell:
        signal_type = "buy"
    elif has_sell and not has_buy:
        signal_type = "sell"
    elif has_sell and has_buy:
        signal_type = "sell"  # Ambiguous, lean sell
    else:
        return None  # Info/noise

    # Price
    price_match = PRICE_RE.search(content)
    price = float(price_match.group(1)) if price_match else None

    # Options
    option_match = OPTION_RE.search(content)
    option_type = None
    strike = None
    expiry = None
    if option_match:
        expiry = option_match.group(1)
        strike = float(option_match.group(2))
        option_type = "call" if option_match.group(3).lower() == "c" else "put"

    # Percentage (for partial exits)
    pct_match = PCT_RE.search(content)
    exit_pct = int(pct_match.group(1)) / 100.0 if pct_match else None

    # Target and stop
    target_match = TARGET_RE.search(content)
    target = float(target_match.group(1)) if target_match else None
    stop_match = STOP_RE.search(content)
    stop = float(stop_match.group(1)) if stop_match else None

    return {
        "ticker": ticker,
        "signal_type": signal_type,
        "price": price,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "exit_pct": exit_pct,
        "target": target,
        "stop_loss": stop,
        "timestamp": posted_at,
        "raw_message": content,
    }


# ── Discord Fetching ────────────────────────────────────────────────────────

async def fetch_discord_history(token: str, channel_id: str, lookback_days: int = 730) -> list[dict]:
    """Fetch message history from Discord REST API."""
    import httpx

    headers = {"Authorization": f"Bot {token}"}
    base_url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    messages = []
    before = None

    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            params = {"limit": 100}
            if before:
                params["before"] = before

            resp = await client.get(base_url, headers=headers, params=params)
            if resp.status_code == 429:
                import asyncio
                retry_after = resp.json().get("retry_after", 5)
                await asyncio.sleep(retry_after)
                continue

            if resp.status_code != 200:
                print(f"Discord API error {resp.status_code}: {resp.text[:200]}")
                break

            batch = resp.json()
            if not batch:
                break

            for msg in batch:
                ts = datetime.fromisoformat(msg["timestamp"].replace("+00:00", "+00:00"))
                if ts < since:
                    return messages
                messages.append({
                    "content": msg["content"],
                    "author": msg["author"]["username"],
                    "timestamp": ts,
                    "message_id": msg["id"],
                })

            before = batch[-1]["id"]

            if len(batch) < 100:
                break

    return messages


# ── Trade Reconstruction ────────────────────────────────────────────────────

def reconstruct_trades(signals: list[dict]) -> list[dict]:
    """Pair buy signals with subsequent sell signals to form complete trades."""
    signals = sorted(signals, key=lambda s: s["timestamp"])
    open_positions: dict[str, list] = {}
    trades = []
    trade_id = 0

    for sig in signals:
        ticker = sig["ticker"]

        if sig["signal_type"] == "buy":
            if ticker not in open_positions:
                open_positions[ticker] = []
            open_positions[ticker].append({
                "entry_signal": sig,
                "exits": [],
                "cumulative_exit_pct": 0.0,
            })

        elif sig["signal_type"] == "sell" and ticker in open_positions and open_positions[ticker]:
            position = open_positions[ticker][-1]
            exit_pct = sig.get("exit_pct") or 1.0
            remaining = 1.0 - position["cumulative_exit_pct"]
            actual_pct = min(exit_pct, remaining)

            position["exits"].append({
                "price": sig.get("price"),
                "pct": actual_pct,
                "cumulative": position["cumulative_exit_pct"] + actual_pct,
                "time": sig["timestamp"],
                "raw_message": sig["raw_message"],
            })
            position["cumulative_exit_pct"] += actual_pct

            if position["cumulative_exit_pct"] >= 0.95:
                trade_id += 1
                trade = _build_trade_row(trade_id, position)
                if trade:
                    trades.append(trade)
                open_positions[ticker].pop()
                if not open_positions[ticker]:
                    del open_positions[ticker]

    # Close remaining open positions as incomplete
    for ticker, positions in open_positions.items():
        for position in positions:
            if position["exits"]:
                trade_id += 1
                trade = _build_trade_row(trade_id, position)
                if trade:
                    trades.append(trade)

    return trades


def _build_trade_row(trade_id: int, position: dict) -> Optional[dict]:
    entry = position["entry_signal"]
    exits = position["exits"]

    if not entry.get("price"):
        return None

    entry_price = entry["price"]

    # Partial exit columns
    exit_25 = exit_50 = exit_75 = exit_100 = None
    for ex in exits:
        if ex["cumulative"] <= 0.30 and ex["price"]:
            exit_25 = ex["price"]
        if 0.30 < ex["cumulative"] <= 0.55 and ex["price"]:
            exit_50 = ex["price"]
        if 0.55 < ex["cumulative"] <= 0.80 and ex["price"]:
            exit_75 = ex["price"]
        if ex["cumulative"] > 0.80 and ex["price"]:
            exit_100 = ex["price"]

    # Weighted average exit price
    total_weight = 0
    weighted_sum = 0
    for ex in exits:
        if ex["price"]:
            weighted_sum += ex["price"] * ex["pct"]
            total_weight += ex["pct"]

    weighted_exit = weighted_sum / total_weight if total_weight > 0 else None

    # P&L
    pnl_pct = ((weighted_exit - entry_price) / entry_price) if weighted_exit else None

    # Profit label: profitable if >50% of position exited with gain
    profitable_weight = sum(
        ex["pct"] for ex in exits
        if ex["price"] and ex["price"] > entry_price
    )
    is_profitable = profitable_weight > 0.5 * total_weight if total_weight > 0 else False

    # Hold duration
    exit_time_final = exits[-1]["time"] if exits else None
    hold_hours = None
    if exit_time_final:
        hold_hours = (exit_time_final - entry["timestamp"]).total_seconds() / 3600

    return {
        "trade_id": f"T{trade_id:05d}",
        "ticker": entry["ticker"],
        "side": "long",
        "entry_price": entry_price,
        "entry_time": entry["timestamp"],
        "target_price": entry.get("target"),
        "stop_loss": entry.get("stop_loss"),
        "exit_pct_25": exit_25,
        "exit_pct_50": exit_50,
        "exit_pct_75": exit_75,
        "exit_pct_100": exit_100,
        "exit_time_first": exits[0]["time"] if exits else None,
        "exit_time_final": exit_time_final,
        "weighted_exit_price": weighted_exit,
        "pnl_pct": pnl_pct,
        "is_profitable": is_profitable,
        "hold_duration_hours": hold_hours,
        "entry_message_raw": entry["raw_message"],
        "exit_messages_raw": json.dumps([e["raw_message"] for e in exits]),
        "analyst": entry.get("author", "unknown"),
        "channel": "",
        "option_type": entry.get("option_type"),
        "strike": entry.get("strike"),
        "expiry": entry.get("expiry"),
    }


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Transform Discord messages into trade rows")
    parser.add_argument("--config", required=True, help="Path to config.json")
    parser.add_argument("--output", required=True, help="Output parquet path")
    parser.add_argument("--messages-file", help="Use pre-fetched messages JSON instead of Discord API")
    args = parser.parse_args()

    with open(args.config) as f:
        config = json.load(f)

    channel_name = config.get("channel_name", "unknown")

    # Fetch or load messages
    if args.messages_file:
        with open(args.messages_file) as f:
            raw_messages = json.load(f)
        for m in raw_messages:
            if isinstance(m["timestamp"], str):
                m["timestamp"] = datetime.fromisoformat(m["timestamp"])
    else:
        import asyncio
        raw_messages = asyncio.run(fetch_discord_history(
            token=config["discord_token"],
            channel_id=config["channel_id"],
            lookback_days=config.get("lookback_days", 730),
        ))

    print(f"Fetched {len(raw_messages)} messages from {channel_name}")

    # Parse signals
    signals = []
    for msg in raw_messages:
        sig = parse_signal(msg["content"], msg["timestamp"])
        if sig:
            sig["author"] = msg.get("author", "unknown")
            signals.append(sig)

    print(f"Parsed {len(signals)} trade signals ({len(raw_messages) - len(signals)} noise filtered)")

    # Reconstruct trades
    trades = reconstruct_trades(signals)
    print(f"Reconstructed {len(trades)} complete trades")

    if not trades:
        print("WARNING: No trades reconstructed. Check signal parsing.")
        df = pd.DataFrame(columns=["trade_id", "ticker", "is_profitable"])
    else:
        df = pd.DataFrame(trades)
        df["channel"] = channel_name

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(output_path, index=False)
    print(f"Saved {len(df)} trades to {output_path}")

    # Summary stats
    if len(df) > 0 and "is_profitable" in df.columns:
        win_rate = df["is_profitable"].mean()
        avg_pnl = df["pnl_pct"].mean() if "pnl_pct" in df.columns else 0
        print(f"Win rate: {win_rate:.1%}, Avg P&L: {avg_pnl:.2%}")


if __name__ == "__main__":
    main()

"""Backtest simulation engine.

Processes messages in timestamp order, parses trade signals, tracks virtual positions,
and matches SELL signals for exits. Positions without matching SELL close at 0 PnL.
"""
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from services.trade_parser.src.parser import parse_trade_message

OPTIONS_MULTIPLIER = 100


def _position_key(ticker: str, strike: float, option_type: str, _expiration: str | None = None) -> str:
    """Match positions by ticker+strike+option_type only (SELL msgs often omit expiration)."""
    return f"{ticker}|{strike}|{option_type}"


def _resolve_qty(qty: int | str) -> int:
    if isinstance(qty, int):
        return max(1, qty)
    if isinstance(qty, str) and qty.endswith("%"):
        return 1
    try:
        return max(1, int(float(qty)))
    except (ValueError, TypeError):
        return 1


@dataclass
class OpenPosition:
    ticker: str
    strike: float
    option_type: str
    expiration: str | None
    entry_price: float
    entry_ts: datetime
    quantity: int
    raw_message: str

    def key(self) -> str:
        return _position_key(self.ticker, self.strike, self.option_type, self.expiration)


@dataclass
class SimulatedTrade:
    trade_id: str
    ticker: str
    strike: float
    option_type: str
    expiration: str | None
    action: str
    quantity: int | str
    entry_price: float
    exit_price: float | None
    entry_ts: datetime
    exit_ts: datetime | None
    exit_reason: str | None
    realized_pnl: float | None
    raw_message: str | None


def run_backtest(
    messages: list[dict],
    profit_target: float = 0.30,
    stop_loss: float = 0.20,
) -> tuple[list[dict], dict]:
    """
    Run backtest simulation over messages.

    Args:
        messages: List of {content, timestamp, author, message_id}
        profit_target: Take profit threshold (e.g. 0.30 = 30%)
        stop_loss: Stop loss threshold (e.g. 0.20 = 20%)

    Returns:
        (trades, summary) - trades are dicts ready for BacktestTrade, summary is the stats JSON.
    """
    # Sort by timestamp ascending
    sorted_msgs = sorted(messages, key=lambda m: m["timestamp"])

    positions: dict[str, list[OpenPosition]] = defaultdict(list)
    trades: list[SimulatedTrade] = []
    total_pnl = 0.0
    winning = 0
    losing = 0
    wins_sum = 0.0
    loss_sum = 0.0
    peak = 0.0
    max_drawdown = 0.0

    for msg in sorted_msgs:
        content = msg.get("content", "").strip()
        if not content:
            continue

        ts = msg["timestamp"]
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        parsed = parse_trade_message(content)
        if not parsed or "actions" not in parsed:
            continue

        raw = parsed.get("raw_message", content)

        for act in parsed["actions"]:
            action = act.get("action", "").upper()
            ticker = act.get("ticker", "")
            strike = float(act.get("strike", 0))
            opt_type = act.get("option_type", "CALL")
            exp = act.get("expiration")
            qty = _resolve_qty(act.get("quantity", 1))
            price = float(act.get("price", 0))

            if not ticker or price <= 0:
                continue

            key = _position_key(ticker, strike, opt_type, exp)

            if action == "BUY":
                pos = OpenPosition(
                    ticker=ticker,
                    strike=strike,
                    option_type=opt_type,
                    expiration=exp,
                    entry_price=price,
                    entry_ts=ts,
                    quantity=qty,
                    raw_message=raw,
                )
                for _ in range(qty):
                    positions[key].append(pos)

            elif action == "SELL":
                stack = positions.get(key, [])
                to_close = min(qty, sum(1 for _ in stack))
                closed = 0

                while closed < to_close and stack:
                    p = stack.pop(0)
                    closed += 1
                    entry = float(p.entry_price)
                    raw_diff = (price - entry) if p.option_type == "CALL" else (entry - price)
                    pnl = raw_diff * OPTIONS_MULTIPLIER
                    total_pnl += pnl
                    if pnl > 0:
                        winning += 1
                        wins_sum += pnl
                    else:
                        losing += 1
                        loss_sum += pnl

                    peak = max(peak, total_pnl)
                    max_drawdown = max(max_drawdown, peak - total_pnl)

                    trades.append(
                        SimulatedTrade(
                            trade_id=str(uuid.uuid4()),
                            ticker=p.ticker,
                            strike=p.strike,
                            option_type=p.option_type,
                            expiration=p.expiration,
                            action="SELL",
                            quantity=1,
                            entry_price=p.entry_price,
                            exit_price=price,
                            entry_ts=p.entry_ts,
                            exit_ts=ts,
                            exit_reason="MANUAL",
                            realized_pnl=pnl,
                            raw_message=p.raw_message,
                        )
                    )

    # Close any remaining positions at 0 PnL
    for key, stack in list(positions.items()):
        end_ts = sorted_msgs[-1]["timestamp"] if sorted_msgs else datetime.now(timezone.utc)
        if end_ts.tzinfo is None:
            end_ts = end_ts.replace(tzinfo=timezone.utc)
        for p in stack:
            trades.append(
                SimulatedTrade(
                    trade_id=str(uuid.uuid4()),
                    ticker=p.ticker,
                    strike=p.strike,
                    option_type=p.option_type,
                    expiration=p.expiration,
                    action="SELL",
                    quantity=1,
                    entry_price=p.entry_price,
                    exit_price=p.entry_price,
                    entry_ts=p.entry_ts,
                    exit_ts=end_ts,
                    exit_reason="EXPIRED",
                    realized_pnl=0.0,
                    raw_message=p.raw_message,
                )
            )
        positions[key] = []

    executed = winning + losing
    total_trades = len(trades)

    avg_win = wins_sum / winning if winning else 0.0
    avg_loss = loss_sum / losing if losing else 0.0
    win_rate = (winning / executed * 100) if executed else 0.0

    gross_profit = wins_sum
    gross_loss = abs(loss_sum)
    profit_factor = (gross_profit / gross_loss) if gross_loss else (gross_profit or 1.0)

    summary = {
        "total_trades": total_trades,
        "executed_trades": executed,
        "winning_trades": winning,
        "losing_trades": losing,
        "total_pnl": round(total_pnl, 2),
        "win_rate_pct": round(win_rate, 1),
        "avg_win": round(avg_win, 2),
        "avg_loss": round(avg_loss, 2),
        "max_drawdown": round(max_drawdown, 2),
        "profit_factor": round(profit_factor, 2),
    }

    trade_dicts = []
    for t in trades:
        trade_dicts.append({
            "trade_id": t.trade_id,
            "ticker": t.ticker,
            "strike": float(t.strike),
            "option_type": t.option_type,
            "expiration": t.expiration,
            "action": t.action,
            "quantity": str(t.quantity),
            "entry_price": float(t.entry_price),
            "exit_price": float(t.exit_price) if t.exit_price is not None else None,
            "entry_ts": t.entry_ts,
            "exit_ts": t.exit_ts,
            "exit_reason": t.exit_reason,
            "realized_pnl": float(t.realized_pnl) if t.realized_pnl is not None else None,
            "raw_message": t.raw_message,
        })

    return trade_dicts, summary

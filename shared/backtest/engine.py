"""Backtest simulation engine.

Processes messages in timestamp order, parses trade signals, tracks virtual positions,
and matches SELL signals for exits. Positions without matching SELL close at 0 PnL.
"""
from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from shared.nlp.signal_parser import parse_signal

OPTIONS_MULTIPLIER = 100


def _position_key(ticker: str, strike: float, option_type: str, _expiration: str | None = None) -> str:
    """Match positions by ticker+strike+option_type only (SELL msgs often omit expiration)."""
    return f"{ticker}|{strike}|{option_type}"


def _resolve_qty(qty: int | str, stack_size: int = 0) -> int:
    """Resolve quantity, treating percentage strings against the open position stack."""
    if isinstance(qty, str) and qty.endswith("%"):
        pct = float(qty.rstrip("%")) / 100.0
        resolved = max(1, round(stack_size * pct)) if stack_size > 0 else 1
        return resolved
    if isinstance(qty, int):
        return max(1, qty)
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

        parsed = parse_signal(content)
        if parsed.signal_type == "noise" or parsed.signal_type == "info":
            continue
        if not parsed.primary_ticker:
            continue

        raw = content

        # V3 parse_signal returns one signal per message (not a list of actions).
        # Map signal_type → action: buy_signal → BUY, sell_signal/close_signal → SELL
        if parsed.signal_type == "buy_signal":
            action = "BUY"
        elif parsed.signal_type in ("sell_signal", "close_signal"):
            action = "SELL"
        else:
            continue

        ticker = parsed.primary_ticker
        strike = float(parsed.option_strike or 0)
        opt_type = (parsed.option_type or "C").upper()
        if opt_type == "C":
            opt_type = "CALL"
        elif opt_type == "P":
            opt_type = "PUT"
        exp = parsed.option_expiry
        raw_qty = 1
        price = float(parsed.price or 0)

        if not ticker or price <= 0:
            continue

        key = _position_key(ticker, strike, opt_type, exp)

        if action == "BUY":
            qty = _resolve_qty(raw_qty)
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
            qty = _resolve_qty(raw_qty, stack_size=len(stack))
            to_close = min(qty, len(stack))
            closed = 0

            while closed < to_close and stack:
                p = stack.pop(0)
                closed += 1
                entry = float(p.entry_price)
                tp_price = entry * (1 + profit_target)
                sl_price = entry * (1 - stop_loss)

                if price >= tp_price:
                    exit_price = tp_price
                    exit_reason = "TAKE_PROFIT"
                elif price <= sl_price:
                    exit_price = sl_price
                    exit_reason = "STOP_LOSS"
                else:
                    exit_price = price
                    exit_reason = "MANUAL"

                raw_diff = exit_price - entry
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
                        exit_price=exit_price,
                        entry_ts=p.entry_ts,
                        exit_ts=ts,
                        exit_reason=exit_reason,
                        realized_pnl=pnl,
                        raw_message=p.raw_message,
                    )
                )

    # Mark remaining positions as EXPIRED at breakeven (no assumption about direction)
    for key, stack in list(positions.items()):
        end_ts = sorted_msgs[-1]["timestamp"] if sorted_msgs else datetime.now(timezone.utc)
        if end_ts.tzinfo is None:
            end_ts = end_ts.replace(tzinfo=timezone.utc)
        for p in stack:
            entry = float(p.entry_price)
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
                    exit_price=entry,
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

"""
Backtest simulation engine — processes bar-by-bar, tracks positions,
and calculates PnL.

M2.7: Core simulation loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SimulationResult:
    equity_curve: list[float] = field(default_factory=list)
    trades: list[dict[str, Any]] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class _Position:
    symbol: str
    side: str
    qty: float
    entry_price: float
    entry_time: Any = None

    @property
    def is_long(self) -> bool:
        return self.side == "long"

    def unrealized_pnl(self, current_price: float) -> float:
        direction = 1.0 if self.is_long else -1.0
        return direction * (current_price - self.entry_price) * self.qty


class SimulationEngine:
    """Bar-by-bar backtest simulation with position tracking."""

    def __init__(self, commission_rate: float = 0.001):
        self._commission_rate = commission_rate

    def run(
        self,
        strategy: Callable[[pd.Series, dict[str, Any]], dict[str, Any] | None],
        data: pd.DataFrame,
        initial_capital: float = 100_000.0,
    ) -> SimulationResult:
        """Run the simulation over the provided OHLCV DataFrame.

        ``strategy`` is called on each bar with (bar, context) and may return
        a signal dict with keys: action (buy/sell/close), qty, symbol.
        """
        capital = initial_capital
        position: _Position | None = None
        trades: list[dict[str, Any]] = []
        equity_curve: list[float] = []

        context: dict[str, Any] = {
            "capital": capital,
            "position": None,
            "bar_index": 0,
        }

        for idx, bar in data.iterrows():
            price = bar["close"]
            context["bar_index"] = idx
            context["capital"] = capital
            context["position"] = (
                {"side": position.side, "qty": position.qty, "entry": position.entry_price}
                if position
                else None
            )

            signal = strategy(bar, context)

            if signal and isinstance(signal, dict):
                action = signal.get("action", "")
                qty = signal.get("qty", 0)

                if action == "buy" and position is None and qty > 0:
                    cost = price * qty * (1 + self._commission_rate)
                    if cost <= capital:
                        position = _Position(
                            symbol=signal.get("symbol", ""),
                            side="long", qty=qty,
                            entry_price=price, entry_time=bar.get("time"),
                        )
                        capital -= cost

                elif action == "sell" and position is None and qty > 0:
                    proceeds = price * qty
                    commission = proceeds * self._commission_rate
                    position = _Position(
                        symbol=signal.get("symbol", ""),
                        side="short", qty=qty,
                        entry_price=price, entry_time=bar.get("time"),
                    )
                    capital += proceeds - commission

                elif action == "close" and position is not None:
                    pnl = position.unrealized_pnl(price)
                    commission = price * position.qty * self._commission_rate
                    capital += pnl - commission + (
                        position.entry_price * position.qty if position.is_long else 0
                    )
                    trades.append({
                        "symbol": position.symbol,
                        "side": position.side,
                        "qty": position.qty,
                        "entry_price": position.entry_price,
                        "exit_price": price,
                        "pnl": pnl - commission,
                        "entry_time": str(position.entry_time),
                        "exit_time": str(bar.get("time")),
                    })
                    position = None

            mark_to_market = capital
            if position:
                mark_to_market += position.unrealized_pnl(price)
                if position.is_long:
                    mark_to_market += position.entry_price * position.qty
            equity_curve.append(mark_to_market)

        total_return = (equity_curve[-1] / initial_capital - 1) if equity_curve else 0.0

        return SimulationResult(
            equity_curve=equity_curve,
            trades=trades,
            metrics={
                "initial_capital": initial_capital,
                "final_equity": equity_curve[-1] if equity_curve else initial_capital,
                "total_return": total_return,
                "total_trades": len(trades),
            },
        )

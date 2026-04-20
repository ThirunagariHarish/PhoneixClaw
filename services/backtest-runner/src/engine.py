"""
Backtesting engine — runs signal-driven and heartbeat-driven backtests.

M2.3: Sandboxed backtesting for agents and strategies.
Reference: PRD Section 11, ArchitecturePlan §3.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class BacktestType(str, Enum):
    SIGNAL_DRIVEN = "signal_driven"
    HEARTBEAT_DRIVEN = "heartbeat_driven"
    WALK_FORWARD = "walk_forward"


class BacktestMetrics:
    """Calculates 15 standard backtest metrics."""

    @staticmethod
    def calculate(trades: list[dict]) -> dict[str, Any]:
        if not trades:
            return {
                "total_trades": 0, "win_rate": 0, "loss_rate": 0,
                "avg_win": 0, "avg_loss": 0, "profit_factor": 0,
                "sharpe_ratio": 0, "sortino_ratio": 0, "max_drawdown": 0,
                "max_drawdown_pct": 0, "total_pnl": 0, "avg_trade_pnl": 0,
                "best_trade": 0, "worst_trade": 0, "avg_hold_time_minutes": 0,
            }

        pnls = [t.get("pnl", 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p < 0]
        total_pnl = sum(pnls)

        win_rate = len(wins) / len(pnls) if pnls else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses and sum(losses) != 0 else float("inf")

        # Drawdown calculation
        cumulative = []
        running = 0
        peak = 0
        max_dd = 0
        for p in pnls:
            running += p
            cumulative.append(running)
            if running > peak:
                peak = running
            dd = peak - running
            if dd > max_dd:
                max_dd = dd

        # Simplified Sharpe (annualized, assuming daily trades)
        import statistics
        sharpe = 0
        if len(pnls) > 1:
            mean_r = statistics.mean(pnls)
            std_r = statistics.stdev(pnls)
            sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0

        return {
            "total_trades": len(trades),
            "win_rate": round(win_rate, 4),
            "loss_rate": round(1 - win_rate, 4),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "sharpe_ratio": round(sharpe, 2),
            "sortino_ratio": None,
            "max_drawdown": round(max_dd, 2),
            "max_drawdown_pct": round(max_dd / peak * 100, 2) if peak > 0 else 0,
            "total_pnl": round(total_pnl, 2),
            "avg_trade_pnl": round(total_pnl / len(trades), 2),
            "best_trade": round(max(pnls), 2),
            "worst_trade": round(min(pnls), 2),
            "avg_hold_time_minutes": None,
        }


class BacktestEngine:
    """
    Runs backtests in a sandboxed environment.
    Supports signal-driven (replay historical signals) and heartbeat-driven (strategy) modes.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    async def run_signal_driven(
        self,
        agent_config: dict,
        historical_signals: list[dict],
        initial_capital: float = 100000.0,
    ) -> dict[str, Any]:
        """
        Replay historical signals through an agent's evaluation logic.
        Each signal is processed as if it arrived in real-time.
        """
        trades = []
        capital = initial_capital

        for signal in historical_signals:
            # Simplified: evaluate each signal and simulate a trade
            decision = self._evaluate_signal(agent_config, signal)
            if decision.get("take_trade"):
                trade = self._simulate_trade(signal, decision, capital)
                trades.append(trade)
                capital += trade.get("pnl", 0)

        metrics = BacktestMetrics.calculate(trades)
        return {
            "type": BacktestType.SIGNAL_DRIVEN.value,
            "config": agent_config,
            "signal_count": len(historical_signals),
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
            "trades": trades,
            "metrics": metrics,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def run_heartbeat_driven(
        self,
        strategy_config: dict,
        market_data: list[dict],
        initial_capital: float = 100000.0,
    ) -> dict[str, Any]:
        """
        Run a heartbeat-driven strategy against historical market data.
        The strategy evaluates at each data point (candle/tick).
        """
        trades = []
        capital = initial_capital

        for bar in market_data:
            decision = self._evaluate_bar(strategy_config, bar, capital)
            if decision.get("take_trade"):
                trade = self._simulate_trade(bar, decision, capital)
                trades.append(trade)
                capital += trade.get("pnl", 0)

        metrics = BacktestMetrics.calculate(trades)
        return {
            "type": BacktestType.HEARTBEAT_DRIVEN.value,
            "config": strategy_config,
            "bar_count": len(market_data),
            "initial_capital": initial_capital,
            "final_capital": round(capital, 2),
            "trades": trades,
            "metrics": metrics,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _evaluate_signal(self, config: dict, signal: dict) -> dict:
        """Evaluate a single signal (placeholder for OpenClaw agent evaluation)."""
        return {"take_trade": True, "side": "buy", "confidence": 0.7}

    def _evaluate_bar(self, config: dict, bar: dict, capital: float) -> dict:
        """Evaluate a market data bar (placeholder for strategy logic)."""
        return {"take_trade": False}

    def _simulate_trade(self, data: dict, decision: dict, capital: float) -> dict:
        """Execute a trade using entry/exit prices from the data bar."""
        entry = data.get("price", data.get("close", 0))
        exit_price = data.get("exit_price", data.get("next_close", entry))
        if entry == 0:
            raise NotImplementedError(
                "_simulate_trade requires 'price' or 'close' in data; "
                "no real market data provided"
            )
        side = decision.get("side", "buy")
        pnl = round((exit_price - entry) if side == "buy" else (entry - exit_price), 2)
        return {
            "symbol": data.get("symbol", "SPY"),
            "side": side,
            "entry_price": entry,
            "exit_price": exit_price,
            "pnl": pnl,
            "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        }

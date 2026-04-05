"""
Walk-forward backtesting — rolling train/test evaluation with optimization.

M3.11: Walk-forward and strategy optimizer.
Reference: PRD Section 11.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class WalkForwardConfig:
    """Configuration for walk-forward backtest."""
    def __init__(
        self,
        train_period_days: int = 252,
        test_period_days: int = 63,
        step_days: int = 21,
        min_trades_per_window: int = 20,
    ):
        self.train_period_days = train_period_days
        self.test_period_days = test_period_days
        self.step_days = step_days
        self.min_trades_per_window = min_trades_per_window


class StrategyOptimizer:
    """
    Optimizes strategy parameters using grid search or Bayesian optimization.
    """

    def __init__(self, param_space: dict[str, list] | None = None):
        self.param_space = param_space or {}

    def grid_search(self, evaluate_fn, data: list) -> dict[str, Any]:
        """Exhaustive grid search over parameter space."""
        best_result = None
        best_params = {}
        combinations = self._generate_combinations()

        for params in combinations:
            result = evaluate_fn(params, data)
            score = result.get("sharpe_ratio", 0)
            if best_result is None or score > best_result.get("sharpe_ratio", 0):
                best_result = result
                best_params = params

        return {
            "best_params": best_params,
            "best_result": best_result,
            "combinations_tested": len(combinations),
        }

    def _generate_combinations(self) -> list[dict]:
        """Generate all parameter combinations."""
        if not self.param_space:
            return [{}]
        keys = list(self.param_space.keys())
        values = list(self.param_space.values())

        def _recurse(idx, current):
            if idx == len(keys):
                return [dict(current)]
            combos = []
            for v in values[idx]:
                current[keys[idx]] = v
                combos.extend(_recurse(idx + 1, current))
            return combos

        return _recurse(0, {})


class WalkForwardEngine:
    """
    Runs walk-forward analysis: train on window N, test on window N+1, step forward.
    Detects overfitting by comparing in-sample vs out-of-sample performance.
    """

    def __init__(self, config: WalkForwardConfig | None = None):
        self.config = config or WalkForwardConfig()

    async def run(self, strategy_config: dict, market_data: list[dict]) -> dict[str, Any]:
        """Execute walk-forward analysis."""
        windows = self._create_windows(len(market_data))
        results = []

        for i, (train_start, train_end, test_start, test_end) in enumerate(windows):
            train_data = market_data[train_start:train_end]
            test_data = market_data[test_start:test_end]

            train_metrics = self._evaluate(strategy_config, train_data)
            test_metrics = self._evaluate(strategy_config, test_data)

            results.append({
                "window": i + 1,
                "train_period": {"start": train_start, "end": train_end, "bars": len(train_data)},
                "test_period": {"start": test_start, "end": test_end, "bars": len(test_data)},
                "in_sample": train_metrics,
                "out_of_sample": test_metrics,
            })

        # Overfitting detection
        avg_is_sharpe = sum(r["in_sample"].get("sharpe_ratio", 0) for r in results) / max(len(results), 1)
        avg_oos_sharpe = sum(r["out_of_sample"].get("sharpe_ratio", 0) for r in results) / max(len(results), 1)
        overfitting_ratio = avg_oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 0

        return {
            "type": "walk_forward",
            "config": {
                "train_days": self.config.train_period_days,
                "test_days": self.config.test_period_days,
                "step_days": self.config.step_days,
            },
            "windows": results,
            "summary": {
                "total_windows": len(results),
                "avg_in_sample_sharpe": round(avg_is_sharpe, 2),
                "avg_out_of_sample_sharpe": round(avg_oos_sharpe, 2),
                "overfitting_ratio": round(overfitting_ratio, 2),
                "is_overfitted": overfitting_ratio < 0.5,
            },
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    def _create_windows(self, total_bars: int) -> list[tuple[int, int, int, int]]:
        """Create rolling train/test windows."""
        windows = []
        train_size = self.config.train_period_days
        test_size = self.config.test_period_days
        step = self.config.step_days
        i = 0

        while i + train_size + test_size <= total_bars:
            windows.append((i, i + train_size, i + train_size, i + train_size + test_size))
            i += step

        return windows

    def _evaluate(self, config: dict, data: list) -> dict:
        """Evaluate strategy on a data window. Not yet implemented — returns zeros."""
        raise NotImplementedError(
            "_evaluate requires a real strategy evaluation implementation; "
            "random placeholder has been removed"
        )

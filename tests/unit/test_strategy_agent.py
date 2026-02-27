from datetime import datetime

import numpy as np
import pandas as pd
from services.strategy_agent.src.backtest_engine import run_backtest
from services.strategy_agent.src.benchmark_comparer import compare_with_benchmarks
from services.strategy_agent.src.report_generator import _generate_pseudocode


def _make_df(n=252):
    dates = pd.bdate_range(end=datetime.now(), periods=n)
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    return pd.DataFrame({
        "date": dates,
        "open": prices * 0.999,
        "high": prices * 1.01,
        "low": prices * 0.99,
        "close": prices,
        "volume": np.random.randint(1_000_000, 5_000_000, n),
    })


class TestBacktestEngine:
    def test_backtest_returns_metrics(self):
        df = _make_df()
        config = {
            "entry_rules": [{"indicator": "sma_crossover", "fast": 10, "slow": 30}],
            "exit_rules": [{"indicator": "sma_crossover", "fast": 10, "slow": 30}],
            "direction": "long",
        }
        result = run_backtest(df, config)
        assert "error" not in result
        assert "equity_curve" in result
        assert "trades" in result
        assert "total_return_pct" in result
        assert "sharpe_ratio" in result
        assert "max_drawdown_pct" in result
        assert "win_rate" in result
        assert "num_trades" in result
        assert "profit_factor" in result

    def test_backtest_equity_starts_at_initial(self):
        df = _make_df()
        config = {"direction": "long"}
        result = run_backtest(df, config, initial_capital=50000)
        assert result["equity_curve"][0] == 50000

    def test_empty_data_returns_error(self):
        df = pd.DataFrame()
        result = run_backtest(df, {})
        assert "error" in result


class TestBenchmarkComparer:
    def test_compare_returns_benchmarks(self):
        metrics = {"total_return_pct": 15.0, "sharpe_ratio": 1.2}
        result = compare_with_benchmarks(metrics, "SPY", 2)
        assert "benchmarks" in result
        assert "strategy" in result


class TestReportGenerator:
    def test_pseudocode_generation(self):
        config = {
            "name": "Test Strategy",
            "entry_rules": [{"indicator": "sma_crossover", "fast": 10, "slow": 30}],
            "exit_rules": [{"indicator": "sma_crossover", "fast": 10, "slow": 30}],
            "ticker": "SPY",
            "direction": "long",
        }
        code = _generate_pseudocode(config)
        assert "ENTRY" in code or "entry" in code.lower()
        assert len(code) > 20

import statistics

from services.backtest_runner.src.engine import BacktestMetrics


def _trades(pnls: list[float]) -> list[dict]:
    return [{"pnl": p} for p in pnls]


class TestCalculateSharpe:
    def test_sharpe_with_known_returns(self):
        pnls = [10.0, 20.0, -5.0, 15.0, 8.0]
        result = BacktestMetrics.calculate(_trades(pnls))
        mean_r = statistics.mean(pnls)
        std_r = statistics.stdev(pnls)
        expected = round((mean_r / std_r) * (252 ** 0.5), 2)
        assert result["sharpe_ratio"] == expected

    def test_sharpe_zero_for_no_variance(self):
        result = BacktestMetrics.calculate(_trades([10.0]))
        assert result["sharpe_ratio"] == 0

    def test_sharpe_zero_for_empty(self):
        result = BacktestMetrics.calculate([])
        assert result["sharpe_ratio"] == 0


class TestCalculateMaxDrawdown:
    def test_max_drawdown_known_curve(self):
        pnls = [100, 50, -200, 30, -50]
        result = BacktestMetrics.calculate(_trades(pnls))
        assert result["max_drawdown"] > 0

    def test_max_drawdown_no_losses(self):
        pnls = [10, 20, 30]
        result = BacktestMetrics.calculate(_trades(pnls))
        assert result["max_drawdown"] == 0

    def test_max_drawdown_all_losses(self):
        pnls = [-10, -20, -30]
        result = BacktestMetrics.calculate(_trades(pnls))
        # Cumulative: -10, -30, -60; peak stays 0; max dd = 0 - (-60) = 60
        assert result["max_drawdown"] == 60


class TestCalculateWinRate:
    def test_win_rate_known(self):
        pnls = [10.0, -5.0, 20.0, -3.0, 15.0]
        result = BacktestMetrics.calculate(_trades(pnls))
        assert result["win_rate"] == round(3 / 5, 4)

    def test_win_rate_all_winners(self):
        result = BacktestMetrics.calculate(_trades([10, 20, 30]))
        assert result["win_rate"] == 1.0

    def test_win_rate_all_losers(self):
        result = BacktestMetrics.calculate(_trades([-10, -20]))
        assert result["win_rate"] == 0.0


class TestCalculateProfitFactor:
    def test_profit_factor_known(self):
        pnls = [100.0, -50.0, 80.0, -30.0]
        result = BacktestMetrics.calculate(_trades(pnls))
        expected = round(abs((100 + 80) / (-50 + -30)), 2)
        assert result["profit_factor"] == expected

    def test_profit_factor_no_losses_is_inf(self):
        result = BacktestMetrics.calculate(_trades([10, 20, 30]))
        assert result["profit_factor"] == float("inf")

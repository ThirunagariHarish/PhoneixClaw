import logging

from .data_fetcher import fetch_historical_data

logger = logging.getLogger(__name__)


async def compare_with_benchmarks(
    backtest_result: dict,
    ticker: str,
    period_years: int = 2,
) -> dict:
    """Compare strategy performance against SPY and buy-and-hold."""
    comparisons = {}

    try:
        spy_data = await fetch_historical_data("SPY", period_years)
        if not spy_data.empty:
            spy_return = (spy_data["close"].iloc[-1] - spy_data["close"].iloc[0]) / spy_data["close"].iloc[0]
            comparisons["spy"] = {
                "total_return_pct": float(spy_return * 100),
                "name": "S&P 500 (SPY)",
            }
    except Exception:
        logger.warning("Failed to fetch SPY benchmark")

    try:
        ticker_data = await fetch_historical_data(ticker, period_years)
        if not ticker_data.empty:
            bh_return = (ticker_data["close"].iloc[-1] - ticker_data["close"].iloc[0]) / ticker_data["close"].iloc[0]
            comparisons["buy_hold"] = {
                "total_return_pct": float(bh_return * 100),
                "name": f"Buy & Hold {ticker}",
            }
    except Exception:
        logger.warning("Failed to compute buy-and-hold for %s", ticker)

    strategy_return = backtest_result.get("total_return_pct", 0)
    spy_return_pct = comparisons.get("spy", {}).get("total_return_pct", 0)
    alpha = strategy_return - spy_return_pct

    comparisons["strategy"] = {
        "total_return_pct": strategy_return,
        "name": "Your Strategy",
    }
    comparisons["alpha"] = alpha

    return comparisons

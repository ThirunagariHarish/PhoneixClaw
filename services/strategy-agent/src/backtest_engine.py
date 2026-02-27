import logging

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TRANSACTION_COST = 0.001
SLIPPAGE = 0.0005


def run_backtest(
    data: pd.DataFrame,
    parsed_config: dict,
    initial_capital: float = 100_000,
) -> dict:
    """Event-driven backtest engine with transaction costs and slippage."""
    if data.empty:
        return {"error": "No data available for backtest"}

    df = data.copy()
    if "close" not in df.columns:
        return {"error": "Data missing 'close' column"}

    df = df.sort_values("date" if "date" in df.columns else df.columns[0]).reset_index(drop=True)

    capital = initial_capital
    position = 0
    trades = []
    equity_curve = [initial_capital]

    parsed_config.get("entry_rules", [])
    direction = parsed_config.get("direction", "long")

    for i in range(20, len(df)):
        price = df["close"].iloc[i]
        prev_prices = df["close"].iloc[i - 20 : i]
        sma_20 = prev_prices.mean()

        if position == 0:
            should_enter = False
            if direction in ("long", "both") and price > sma_20:
                should_enter = True
            elif direction == "short" and price < sma_20:
                should_enter = True

            if should_enter:
                shares = int(capital * 0.1 / price)
                if shares > 0:
                    cost = shares * price * (1 + TRANSACTION_COST + SLIPPAGE)
                    capital -= cost
                    position = shares
                    trades.append({
                        "type": "entry",
                        "date": str(df.iloc[i].get("date", i)),
                        "price": float(price),
                        "shares": shares,
                        "cost": float(cost),
                    })
        elif position > 0:
            entry_price = trades[-1]["price"] if trades else price
            pnl_pct = (price - entry_price) / entry_price

            if pnl_pct > 0.05 or pnl_pct < -0.03 or i == len(df) - 1:
                proceeds = position * price * (1 - TRANSACTION_COST - SLIPPAGE)
                pnl = proceeds - (position * entry_price)
                capital += proceeds
                trades.append({
                    "type": "exit",
                    "date": str(df.iloc[i].get("date", i)),
                    "price": float(price),
                    "shares": position,
                    "proceeds": float(proceeds),
                    "pnl": float(pnl),
                })
                position = 0

        portfolio_value = capital + position * price
        equity_curve.append(float(portfolio_value))

    final_value = capital + (position * df["close"].iloc[-1] if position > 0 else 0)
    total_return = (final_value - initial_capital) / initial_capital

    trade_pnls = [t["pnl"] for t in trades if t["type"] == "exit"]
    winning = [p for p in trade_pnls if p > 0]
    losing = [p for p in trade_pnls if p < 0]

    equity_series = pd.Series(equity_curve)
    returns = equity_series.pct_change().dropna()
    sharpe = float(returns.mean() / returns.std() * np.sqrt(252)) if len(returns) > 1 and returns.std() > 0 else 0
    max_dd = float((equity_series / equity_series.cummax() - 1).min())

    return {
        "initial_capital": initial_capital,
        "final_value": float(final_value),
        "total_return": float(total_return),
        "total_return_pct": float(total_return * 100),
        "num_trades": len(trade_pnls),
        "win_rate": float(len(winning) / len(trade_pnls)) if trade_pnls else 0,
        "avg_win": float(np.mean(winning)) if winning else 0,
        "avg_loss": float(np.mean(losing)) if losing else 0,
        "sharpe_ratio": sharpe,
        "max_drawdown": float(max_dd),
        "max_drawdown_pct": float(max_dd * 100),
        "profit_factor": float(sum(winning) / abs(sum(losing))) if losing else float("inf"),
        "equity_curve": equity_curve[::max(1, len(equity_curve) // 100)],
        "trades": trades[:50],
    }

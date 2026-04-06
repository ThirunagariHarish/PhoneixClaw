# Exit Optimization Skill

## Goal
Find the optimal exit point for the assigned position by combining technical analysis, market correlation, analyst signals, and risk levels.

## Decision Framework
Each monitoring cycle produces an `exit_urgency` score (0-100) from four sources:

| Source | Max Contribution | Trigger |
|--------|------------------|---------|
| Technical Analysis | 55 | RSI extremes, MACD reversal, BB break, S/R proximity |
| MAG-7 Correlation | 30 | Market moving against position direction |
| Discord Sell Signal | 40 | Analyst posts sell/close/trim for this ticker |
| Risk Levels | 100 | Stop loss hit (forces FULL_EXIT) |

## Action Thresholds
- `urgency < 50` → HOLD (continue monitoring)
- `50 <= urgency < 80` → PARTIAL_EXIT (sell 50%, keep monitoring remainder)
- `urgency >= 80` OR stop loss hit → FULL_EXIT (close immediately)

## Partial Exit Ladder
1. First partial exit at urgency 50-79: sell 50%
2. Set tighter trailing stop on remainder (1.5x ATR instead of 2x)
3. Second partial exit at urgency 60+: sell another 50% of remainder
4. Final exit at urgency 80+ or stop loss hit

## When to be MORE Conservative (lower urgency thresholds)
- Position size > 10% of portfolio
- VIX spiking >5%
- Major economic event within 24 hours (FOMC, CPI, NFP, earnings)
- Position has been profitable >5% (lock in gains)

## When to be MORE Aggressive (higher urgency thresholds)
- Strong trend confirmation (ADX > 30)
- Pattern matches from backtest still active
- MAG-7 strongly aligned with position direction
- High open interest in same direction

## Reporting
Every exit must report to Phoenix with:
- Final P&L (dollar and percentage)
- Exit reasoning (which signals fired)
- Time held
- Maximum favorable excursion (highest profit during hold)
- Maximum adverse excursion (lowest profit during hold)

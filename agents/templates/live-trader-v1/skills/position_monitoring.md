# Skill: Position Monitoring

## Purpose
Continuously monitor open positions using price data and technical analysis to decide when to hold, partially close, or fully exit. Supports both intraday and swing trade management.

## Monitoring Loop

### Every 60 Seconds
- Fetch current price for all open positions
- Update trailing stop levels
- Check if any stop-loss has been triggered
- Update unrealised P&L

### Every 5 Minutes
- Run full technical analysis on each open position:
  - RSI (14-period on 5-min candles)
  - MACD signal line crossover
  - Bollinger Band position
  - Volume trend (increasing/decreasing)
  - Support/resistance proximity
- Decide: HOLD, PARTIAL_CLOSE, or FULL_CLOSE

### Every 15 Minutes
- Re-evaluate conviction on each position
- If technical signals have deteriorated significantly, consider closing regardless of profit target

## Partial Exit Ladder

| Unrealised Gain | Action |
|-----------------|--------|
| +20% | Close 30% of position |
| +30% | Close another 20% (50% total closed) |
| +50% | Close another 25% (75% total closed) |
| Trailing stop hit | Close remaining 25% |

## Trailing Stop

Activates after position is up 10%:
- **Percentage-based**: trail at 70% of maximum unrealised profit
- **ATR-based**: alternative — trail at 2x ATR below highest price
- Use whichever produces a tighter stop

## TA-Based Hold/Close Decisions

When position approaches a profit target, run TA before closing:
- If RSI < 70 and MACD bullish: HOLD (momentum still strong)
- If RSI > 80 or MACD bearish crossover: CLOSE (momentum exhausting)
- If volume declining while price rising: CLOSE (divergence)
- If breaking above resistance: HOLD (potential breakout)

## Analyst Action Monitoring

If the analyst posts a "sell" or "trim" message for the same ticker:
- Treat as high-priority close signal
- Close at least 50% immediately regardless of TA
- Close remaining based on TA analysis

## End of Day

- For intraday (0DTE): close all positions by 3:55 PM ET
- For swing trades: hold overnight unless unrealised loss > 5% (then reduce by 30%)
- Generate daily summary and report to Phoenix

# Trend Follower

## Purpose
Identify and follow established trends using moving averages and momentum indicators.

## Category
strategy

## Triggers
- On new bar close for monitored symbols
- When trend strength exceeds configurable threshold

## Inputs
- symbol: Ticker symbol to analyze (string)
- timeframe: Chart timeframe — 1h, 4h, daily (string)
- fast_period: Fast moving average period, default 20 (int)
- slow_period: Slow moving average period, default 50 (int)
- adx_threshold: Minimum ADX for trend confirmation, default 25 (float)

## Outputs
- trend_direction: Current trend — bullish, bearish, neutral (string)
- signal: Entry signal — long, short, none (string)
- confidence: Signal confidence 0-1 (float)
- entry_price: Suggested entry price (float)
- stop_loss: Suggested stop loss level (float)

## Steps
1. Fetch OHLCV data for the specified symbol and timeframe
2. Calculate fast and slow EMAs
3. Compute ADX to confirm trend strength
4. Determine trend direction from EMA crossover state
5. Generate entry signal when fast crosses slow AND ADX > threshold
6. Calculate stop loss at recent swing low/high
7. Return signal with confidence based on ADX strength

## Example
AAPL daily chart: 20 EMA crosses above 50 EMA with ADX at 32 — generates long signal with 0.78 confidence, stop at previous swing low.

## Notes
- Works best in trending markets; avoid during choppy/range-bound conditions
- Combine with volume confirmation for higher quality signals
- Consider using ATR-based stops instead of swing points for volatile assets

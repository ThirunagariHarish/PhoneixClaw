# Sector RSI Comparison

## Purpose
Relative Strength Index comparing stock vs sector performance to identify relative strength or weakness.

## Category
analysis

## Triggers
- When user requests relative strength of a stock vs its sector
- When screening for sector outperformers or underperformers
- When building sector-rotation or pair-trade signals
- When assessing if a stock is leading or lagging its sector

## Inputs
- `symbol`: string — Stock ticker (e.g., AAPL, NVDA)
- `sector_etf`: string — Sector ETF (e.g., XLK, XLF) or auto-detect from symbol
- `period`: number — RSI period (default: 14)
- `lookback_days`: number — Days for RSI calc (default: 30)
- `ohlcv_stock`: object[] — Optional pre-fetched stock OHLCV
- `ohlcv_sector`: object[] — Optional pre-fetched sector OHLCV

## Outputs
- `stock_rsi`: number — RSI of the stock (0–100)
- `sector_rsi`: number — RSI of the sector ETF (0–100)
- `rsi_spread`: number — stock_rsi - sector_rsi (positive = outperforming)
- `relative_strength`: string — "outperforming", "underperforming", "in_line"
- `metadata`: object — symbol, sector_etf, period, computed_at

## Steps
1. Resolve sector ETF from symbol (e.g., AAPL -> XLK) if not provided
2. Fetch OHLCV for stock and sector (or use provided)
3. Compute RSI for both: RSI = 100 - 100/(1 + RS), RS = avg gain / avg loss
4. rsi_spread = stock_rsi - sector_rsi
5. Classify: spread > 5 = outperforming, < -5 = underperforming, else in_line
6. Return stock_rsi, sector_rsi, rsi_spread, relative_strength, metadata
7. Cache with 1h TTL per symbol

## Example
```
Input: symbol="NVDA", sector_etf="XLK", period=14
Output: {
  stock_rsi: 68,
  sector_rsi: 55,
  rsi_spread: 13,
  relative_strength: "outperforming",
  metadata: {symbol: "NVDA", sector_etf: "XLK", period: 14, computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Use finviz-screener or sector mapping for symbol -> sector ETF
- Outperforming stock in weak sector can still be bearish; combine with trend
- Integrate with sector-rotation-intraday for rotation signals

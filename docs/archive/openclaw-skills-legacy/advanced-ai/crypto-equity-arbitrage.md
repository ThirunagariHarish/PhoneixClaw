# Crypto-Equity Arbitrage

## Purpose
Detect price delays between BTC and crypto-correlated equities (MSTR, MARA, COIN) for arbitrage signals.

## Category
advanced-ai

## Triggers
- When BTC moves >1% in short window and equities lag
- On user request for crypto-equity spread analysis
- When building pairs or relative-value signals
- During high crypto volatility (e.g., ETF flows, regulatory news)

## Inputs
- `btc_price`: number — Current BTC spot price
- `btc_history`: number[] — Recent BTC prices (e.g., last 60 min, 1-min bars)
- `equity_symbols`: string[] — ["MSTR", "MARA", "COIN", "RIOT"] (default)
- `equity_prices`: object — {MSTR: number, MARA: number, ...}
- `equity_history`: object — Per-symbol price history
- `lag_window_minutes`: number — Max lag to consider (default: 15)

## Outputs
- `spread_signals`: object[] — [{symbol, direction, magnitude, lag_minutes, confidence}]
- `arbitrage_opportunity`: boolean — True if actionable spread exists
- `suggested_action`: string — "BUY_MSTR_SELL_BTC" | "NEUTRAL" | etc.
- `correlation_coef`: object — Per-symbol rolling correlation with BTC
- `metadata`: object — btc_move_pct, window_used, timestamp

## Steps
1. Compute BTC return over lag_window (e.g., last 15 min)
2. For each equity: compute return over same window; measure lag (cross-correlation)
3. If BTC up 2% and MSTR flat: MSTR may lag; signal BUY_MSTR or pair trade
4. Compute correlation_coef (rolling) for each equity vs BTC
5. Filter: only signal when correlation > 0.7 and lag > 5 min
6. Set arbitrage_opportunity=true if any spread exceeds threshold
7. Return spread_signals, arbitrage_opportunity, suggested_action, correlation_coef, metadata
8. Downstream can execute pair trade or single-leg based on risk

## Example
```
Input: btc_price=65000, btc_history=[64800,64950,65100,65200], equity_symbols=["MSTR","MARA"],
       equity_prices={MSTR: 420, MARA: 28.5}
Output: {
  spread_signals: [{symbol: "MSTR", direction: "LAG_LONG", magnitude: 1.2, lag_minutes: 8, confidence: 78}],
  arbitrage_opportunity: true,
  suggested_action: "BUY_MSTR",
  correlation_coef: {MSTR: 0.89, MARA: 0.82},
  metadata: {btc_move_pct: 0.62, window_used: 15, timestamp: "2025-03-03T14:30:00Z"}
}
```

## Notes
- MSTR, MARA are highly correlated with BTC; COIN less so (exchange)
- Consider funding rates and borrow costs for true arbitrage
- Use with pairs-trade for execution structure

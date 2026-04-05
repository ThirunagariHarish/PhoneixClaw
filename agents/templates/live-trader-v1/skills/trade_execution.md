# Skill: Trade Execution Pipeline

## Purpose
Orchestrate the full pipeline from parsed signal to executed trade. Ensures every trade is validated by the ML model, matches learned rules, passes risk checks, and is confirmed by technical analysis before execution.

## Pipeline Steps

```
Signal Detected
  → Parse (ticker, price, direction, option type)
  → Enrich (200+ market features via enrich_single.py)
  → Infer (ML model prediction via inference.py)
  → Rule Check (evaluate learned rules, compute weighted score)
  → Risk Check (position limits, daily loss, concurrent positions via risk_check.py)
  → TA Confirmation (technical analysis via technical_analysis.py)
  → Execute (place order via robinhood_mcp.py with stop-loss)
  → Report (send trade details to Phoenix API)
```

## Decision Logic

A trade is executed only if ALL conditions are met:
1. Model confidence >= active mode threshold
2. Rule-weighted score > 0 (net positive pattern match)
3. Risk check passes (within position limits, daily loss limit not exceeded)
4. TA does not show strong counter-signal (e.g., overbought RSI > 85 for a buy)

## Price Buffer
When latency causes price to move from signal price:
- Use `price_buffer_pct` from config (derived from backtesting latency analysis)
- Place limit order at signal_price * (1 + buffer) for buys, signal_price * (1 - buffer) for sells
- If price has moved beyond buffer, log skip with reason "price drift exceeded buffer"

## Rejection Logging
Every rejected signal is logged with full reasoning:
```json
{
  "signal": "BTO SPX 5950C at 12.50",
  "rejected": true,
  "reasons": ["confidence 0.42 below threshold 0.65", "RSI 78 overbought"],
  "model_confidence": 0.42,
  "rule_score": -1.2,
  "matched_rules": ["afternoon_session: -0.5", "high_vix: -0.7"]
}
```

# Candlestick Pattern AI

## Purpose
AI-vision detection of 150+ candlestick patterns using computer vision models on OHLCV charts.

## Category
analysis

## Triggers
- When user requests candlestick pattern scan for a symbol
- When building reversal or continuation signals from chart patterns
- When backtesting pattern-based strategies
- When screening for doji, engulfing, hammer, etc.

## Inputs
- `symbol`: string — Ticker to analyze
- `ohlcv`: object[] — OHLCV bars (or fetch)
- `lookback_bars`: number — Bars for pattern window (default: 50)
- `pattern_set`: string — "all", "reversal", "continuation", or comma-separated list
- `confidence_threshold`: number — Min model confidence (0–1, default: 0.7)
- `chart_image`: string — Optional base64 chart image (skip OHLCV render)

## Outputs
- `patterns`: object[] — [{name, type, direction, confidence, bar_index, metadata}]
- `dominant_signal`: string — "bullish", "bearish", "neutral"
- `pattern_count`: number — Count of detected patterns
- `metadata`: object — symbol, lookback, model_version, computed_at

## Steps
1. Fetch OHLCV or accept chart_image; if OHLCV, render to image (matplotlib/plotly)
2. Run CV model (e.g., fine-tuned ResNet/ViT) on chart image
3. Decode model output: pattern names, types, directions, confidence scores
4. Filter by confidence_threshold and pattern_set
5. Map bar_index to pattern location for backtest alignment
6. Aggregate dominant_signal from pattern directions
7. Return patterns, dominant_signal, pattern_count, metadata
8. Support batch inference for multi-symbol scans

## Example
```
Input: symbol="AAPL", pattern_set="reversal", confidence_threshold=0.75
Output: {
  patterns: [
    {name: "bullish_engulfing", type: "reversal", direction: "bullish", confidence: 0.89, bar_index: 42},
    {name: "hammer", type: "reversal", direction: "bullish", confidence: 0.78, bar_index: 45}
  ],
  dominant_signal: "bullish",
  pattern_count: 2,
  metadata: {symbol: "AAPL", model_version: "v2.1", computed_at: "2025-03-03T15:00:00Z"}
}
```

## Notes
- Requires trained CV model; use model-inference-runner or custom PyTorch
- Pattern set: doji, engulfing, hammer, shooting_star, three_white_soldiers, etc.
- Consider alpha-vantage-technicals for rule-based fallback

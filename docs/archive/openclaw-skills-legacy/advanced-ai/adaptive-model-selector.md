# Adaptive Model Selector

## Purpose
Auto-select best model for current market regime: switch between momentum, mean-reversion, and regime-specific models.

## Category
advanced-ai

## Triggers
- When selecting which strategy or model to use for next signal
- When market regime changes (from macro-regime-detector)
- When user requests adaptive model selection
- Periodically (e.g., daily) to refresh model ranking

## Inputs
- `regime`: object — Output from macro-regime-detector (fed_stance, risk_sentiment, etc.)
- `available_models`: string[] — Model/strategy names (e.g., ["momentum", "mean_reversion", "volatility"])
- `performance_history`: object — Per-model performance by regime (or fetch from backtest)
- `current_metrics`: object — Optional: recent model performance (win rate, Sharpe)
- `selection_criteria`: string — "regime_match", "recent_performance", "ensemble" (default: "regime_match")

## Outputs
- `selected_model`: string — Model to use for current regime
- `ranked_models`: object[] — [{model, score, reason}]
- `regime_model_map`: object — Regime -> preferred model
- `confidence`: number — Confidence in selection (0–1)
- `metadata`: object — regime, criteria, performance_summary

## Steps
1. Load regime from macro-regime-detector or input
2. Load performance_history: per-model stats by regime (backtest or live)
3. If selection_criteria="regime_match": map regime to best historical model
4. If "recent_performance": rank by current_metrics (win rate, Sharpe)
5. If "ensemble": compute weighted combo; select top or blend
6. Build regime_model_map: e.g., risk_on -> momentum, risk_off -> mean_reversion
7. Rank models by score; select top as selected_model
8. confidence = consistency of historical outperformance in similar regimes
9. Return selected_model, ranked_models, regime_model_map, confidence, metadata
10. Pass selected_model to strategy or model-inference-runner

## Example
```
Input: regime={risk_sentiment: "risk_on", fed_stance: "dovish"},
       available_models=["momentum", "mean_reversion", "volatility"],
       selection_criteria="regime_match"
Output: {
  selected_model: "momentum",
  ranked_models: [{model: "momentum", score: 0.92, reason: "Best in risk_on regime"}, ...],
  regime_model_map: {risk_on: "momentum", risk_off: "mean_reversion", neutral: "volatility"},
  confidence: 0.85,
  metadata: {regime: "risk_on_dovish", criteria: "regime_match"}
}
```

## Notes
- Performance_history requires backtest by regime; build from historical data
- Avoid overfitting: use out-of-sample regime performance
- Integrate with macro-regime-detector for automatic regime input

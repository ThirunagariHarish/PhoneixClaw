Provide a detailed side-by-side model comparison with analysis.

1. Read every `*_results.json` file in `output/models/`.
2. Read `output/models/best_model.json` for the selected best model.
3. Read `output/explainability.json` if it exists for feature importance data.

For each model that actually trained (not skipped), show:
- All metrics: accuracy, AUC, F1, precision, recall
- Trading metrics: profit_factor, sharpe_ratio, max_drawdown_pct
- Model-specific info: artifact_path, backend (if present)

Group models by category:
- **Tree-based**: XGBoost, LightGBM, CatBoost, Random Forest
- **Deep Learning**: LSTM, Transformer, TFT, TCN
- **Ensemble**: Hybrid, Meta-Learner

For each category, identify the winner.
Then show the overall best model and explain why it was selected.

If explainability data exists, show the top-10 most important features for the best model.

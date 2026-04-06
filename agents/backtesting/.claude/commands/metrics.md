Read all model result JSON files from `output/models/` and display a comprehensive metrics comparison.

1. Find and read every `*_results.json` file in `output/models/`.
2. Also read `output/models/best_model.json` if it exists.
3. For each model, extract: model_name, accuracy, auc_roc, f1_score (or f1), precision, recall, profit_factor, sharpe_ratio, max_drawdown_pct.
4. If a model has `"skipped": true`, show its skip_reason instead of metrics.

Display results as a formatted comparison table sorted by AUC descending.
Mark the best model with a star (*).

Example format:
```
Model           | Accuracy | AUC    | F1     | Precision | Recall | Sharpe
----------------|----------|--------|--------|-----------|--------|-------
* xgboost       | 0.9915   | 0.9991 | 0.9953 | 0.9920    | 0.9986 | 1.23
  lightgbm      | 0.9915   | 1.0000 | 0.9953 | 0.9920    | 0.9986 | 1.15
  transformer   | SKIPPED (OOM at 512MB limit)
```

After the table, show:
- Total models trained vs skipped
- Best model name and its key metrics
- Any models with AUC below 0.6 (potential issues)

Run a comprehensive diagnostic check on the backtesting pipeline to identify issues.

1. **Check output directory structure**:
   - Does `output/` exist? List all files with sizes.
   - Does `output/models/` exist? List all files with sizes.

2. **Check for missing expected files**:
   - transformed.parquet, enriched.parquet, X_train.npy, y_train.npy, candle_windows.npy
   - At least one *_results.json in models/
   - best_model.json, patterns.json, explainability.json

3. **Check for errors in model results**:
   - Read each *_results.json and check for `"error"` or `"skipped": true` fields
   - Check if any model has accuracy=0 or auc_roc=0 (indicates failure)

4. **Check disk space**: Run `df -h .` to show available space.

5. **Check Python environment**:
   - Run `python3 -c "import torch; print(f'PyTorch {torch.__version__}')"` — is PyTorch available?
   - Run `python3 -c "import xgboost; print(f'XGBoost {xgboost.__version__}')"` — is XGBoost available?
   - Run `python3 -c "import lightgbm; print(f'LightGBM {lightgbm.__version__}')"` — is LightGBM available?

6. **Check data integrity**:
   - Read enriched.parquet and check for columns with 100% NaN
   - Check if y_train has both classes (0 and 1) — if all same class, models will fail

7. **Memory check**: Run `free -m` or `vm_stat` to show available memory.

8. **Summarize findings**: List all issues found with suggested fixes.

Check the current state of the backtesting pipeline and report a clear status summary.

1. Read `config.json` to get the agent and channel info.
2. Look at all files in `output/` and `output/models/` — list which ones exist and their sizes.
3. Determine which pipeline steps have completed by checking for their output files:
   - transform: `output/transformed.parquet`
   - enrich: `output/enriched.parquet`
   - text_embeddings: `output/text_embeddings.npy`
   - preprocess: `output/X_train.npy`
   - train_xgboost: `output/models/xgboost_results.json`
   - train_lightgbm: `output/models/lightgbm_results.json`
   - train_catboost: `output/models/catboost_results.json`
   - train_rf: `output/models/rf_results.json`
   - train_lstm: `output/models/lstm_results.json`
   - train_transformer: `output/models/transformer_results.json`
   - train_tft: `output/models/tft_results.json`
   - train_tcn: `output/models/tcn_results.json`
   - train_hybrid: `output/models/hybrid_results.json`
   - train_meta_learner: `output/models/meta_learner_results.json`
   - evaluate: `output/models/best_model.json`
   - explainability: `output/explainability.json`
   - patterns: `output/patterns.json`
   - llm_patterns: `output/llm_patterns.json`
   - create_live_agent: `output/live_agent/manifest.json`

4. Display a formatted table:
   - Step name | Status (DONE / MISSING / SKIPPED) | Output file | File size
   - Mark SKIPPED if the results JSON exists but contains `"skipped": true`

5. Show overall progress: X of 19 steps completed, estimated percentage.

Re-run a specific pipeline step. The step name is provided as an argument.

Step to retry: $ARGUMENTS

Map the step name to the correct script and arguments:

| Step Name | Command |
|-----------|---------|
| transform | `python3 tools/transform.py --config config.json --output output/transformed.parquet` |
| enrich | `python3 tools/enrich.py --input output/transformed.parquet --output output/enriched.parquet` |
| text_embeddings | `python3 tools/compute_text_embeddings.py --input output/enriched.parquet --output output/` |
| preprocess | `python3 tools/preprocess.py --input output/enriched.parquet --output output/` |
| train_xgboost | `python3 tools/train_xgboost.py --data output/ --output output/models/` |
| train_lightgbm | `python3 tools/train_lightgbm.py --data output/ --output output/models/` |
| train_catboost | `python3 tools/train_catboost.py --data output/ --output output/models/` |
| train_rf | `python3 tools/train_rf.py --data output/ --output output/models/` |
| train_lstm | `python3 tools/train_lstm.py --data output/ --output output/models/` |
| train_transformer | `python3 tools/train_transformer.py --data output/ --output output/models/` |
| train_tft | `python3 tools/train_tft.py --data output/ --output output/models/` |
| train_tcn | `python3 tools/train_tcn.py --data output/ --output output/models/` |
| train_hybrid | `python3 tools/train_hybrid.py --data output/ --output output/models/` |
| train_meta_learner | `python3 tools/train_meta_learner.py --models-dir output/models/ --data output/ --output output/models/` |
| evaluate | `python3 tools/evaluate_models.py --models-dir output/models/ --output output/models/best_model.json` |
| explainability | `python3 tools/build_explainability.py --model output/models/ --data output/ --output output/explainability.json` |
| patterns | `python3 tools/discover_patterns.py --data output/ --output output/patterns.json` |
| llm_patterns | `python3 tools/analyze_patterns_llm.py --data output/ --output output/llm_patterns.json --config config.json` |
| create_live_agent | `python3 tools/create_live_agent.py --config config.json --models output/models/ --output output/live_agent/` |

Instructions:
1. If `$ARGUMENTS` is empty, ask the user which step to retry.
2. Verify the step name is valid (exists in the table above).
3. Check that prerequisite output files exist before running.
4. Run the command and show the full output.
5. After completion, report success/failure and show updated metrics if applicable.
6. Report progress to Phoenix via: `python3 tools/report_to_phoenix.py --step <step> --message "Retried <step>" --progress <pct>`

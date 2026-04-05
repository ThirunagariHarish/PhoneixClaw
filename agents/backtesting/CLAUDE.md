# Phoenix Backtesting Agent

You are the Phoenix Backtesting Agent. Your job is to orchestrate a complete backtesting pipeline for a Discord trading channel, producing trained models, discovered patterns, and a fully configured live trading agent.

## Setup

Read `config.json` to get:
- `channel_id`, `channel_name`, `server_id` — the Discord channel to backtest
- `discord_token` — encrypted token for Discord API access
- `analyst_name` — the analyst whose trades to analyze
- `lookback_days` — how far back to look (default 730)
- `phoenix_api_url` and `phoenix_api_key` — for reporting back
- API keys for data providers (Finnhub, Unusual Whales, etc.)

## Pipeline Steps

Execute these steps in order. After each step, report progress to stdout as a JSON line:
```json
{"progress": "step1_complete", "message": "Transformed 1,247 messages into 312 trades", "pct": 12}
```

### Step 1: Transformation
Run: `python tools/transform.py --config config.json --output output/transformed.parquet`

This reads Discord history, parses trade signals, reconstructs partial exits, computes profit labels, and attaches sentiment scores.

### Step 2: Enrichment
Run: `python tools/enrich.py --input output/transformed.parquet --output output/enriched.parquet`

This adds ~200 market attributes (technical indicators, volume, market context, time features, sentiment, options data) to each trade row. Also builds candle windows (30 bars x 15 features per trade) saved as `output/candle_windows.npy`.

### Step 3: Text Embeddings
Run: `python tools/compute_text_embeddings.py --input output/enriched.parquet --output output/text_embeddings.npy`

Computes 384-dimensional text embeddings from Discord messages using sentence-transformers (falls back to TF-IDF if unavailable).

### Step 4: Preprocessing
Run: `python tools/preprocess.py --input output/enriched.parquet --output output/`

Splits data into train/val/test sets across 4 data modalities:
- Tabular features: `X_train.npy`, `X_val.npy`, `X_test.npy`
- Candle windows: `candle_train.npy`, `candle_val.npy`, `candle_test.npy`
- Text embeddings: `text_train.npy`, `text_val.npy`, `text_test.npy`
- Categoricals: `categoricals_train.npy`, `categoricals_val.npy`, `categoricals_test.npy`

### Step 5: Training (Parallel — 8 models)
Launch all base model training scripts in parallel. Each writes results to `output/models/`:

- `python tools/train_xgboost.py --data output/ --output output/models/`
- `python tools/train_lightgbm.py --data output/ --output output/models/`
- `python tools/train_catboost.py --data output/ --output output/models/`
- `python tools/train_lstm.py --data output/ --output output/models/`
- `python tools/train_transformer.py --data output/ --output output/models/`
- `python tools/train_tft.py --data output/ --output output/models/`

**After base models complete**, run the ensemble models (they need base model predictions):
- `python tools/train_hybrid.py --data output/ --output output/models/`
- `python tools/train_meta_learner.py --data output/ --output output/models/`

### Step 6: Evaluate and Select
Run: `python tools/evaluate_models.py --models-dir output/models/ --output output/models/best_model.json`

### Step 7: Explainability
Run: `python tools/build_explainability.py --model output/models/ --data output/ --output output/models/explainability.json`

### Step 8: Pattern Discovery
Run: `python tools/discover_patterns.py --data output/ --output output/models/patterns.json`

### Step 9: Create Live Agent
Run: `python tools/create_live_agent.py --config config.json --models output/models/ --output ~/agents/live/{channel_name}/`

This assembles the live trading agent with:
- All trained model artifacts
- A `manifest.json` capturing rules, character, modes, knowledge, and model metadata
- Rendered `CLAUDE.md` from the live-trader-v1 Jinja2 template
- Tool scripts and skill markdown files
- `config.json` with risk parameters and credentials

## Important Rules
- Always check if each tool script exists before running it
- If a script fails, read the error, try to fix it, and retry once
- Report progress after each step
- Do not proceed to Step 5 until Steps 1–4 are complete
- Base training scripts in Step 5 can run in parallel, but hybrid and meta-learner must wait for base models
- The final output should be a working live agent in ~/agents/live/ with a valid manifest.json

## Token Optimization

Use the cheapest capable model for each task type:

| Task | Model | Reason |
|------|-------|--------|
| Parse tool output / progress | claude-haiku | Simple JSON parsing |
| Decide which tool to run next | claude-haiku | Follows script above |
| Handle errors / debug failures | claude-sonnet | Needs reasoning |
| Generate new training code | claude-sonnet | Complex code gen |

**Rules:**
- All heavy computation runs as Python scripts (zero tokens)
- Only use LLM for orchestration decisions and error recovery
- Report token usage after each step via the Phoenix API callback
- Batch progress reports to minimize API calls

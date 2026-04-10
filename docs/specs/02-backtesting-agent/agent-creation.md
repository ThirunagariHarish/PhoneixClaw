# Spec: Agent Creation & Backtesting Lifecycle

## Purpose

When a user creates an agent through the dashboard wizard, the system automatically starts backtesting. The backtesting pipeline analyzes historical trading signals, trains ML models, discovers patterns, and prepares the agent for live trading.

## Agent Lifecycle

```
Dashboard Wizard (Channel → Risk → Review → Create)
  → Agent row (status: BACKTESTING) + AgentBacktest row (status: RUNNING)
  → task_runner.py spawns backtesting subprocess
  → Each step updates AgentBacktest.progress_pct and current_step
  → Progress visible in dashboard BacktestProgressPanel
  → Pipeline completes → Agent status: BACKTEST_COMPLETE
  → User reviews results in BacktestReviewDialog
  → User approves (paper or live) → status: PAPER/APPROVED
  → User promotes → status: RUNNING
```

## Two Backtesting Execution Paths

### Path 1: Local Subprocess (Default)

The `task_runner.py` service runs the backtesting pipeline as a local Python subprocess on the API server:

1. Agent creation triggers `run_backtest(agent_id, backtest_id, config)`
2. Pipeline steps execute sequentially: transform → enrich → train → evaluate → patterns
3. Progress is written to `AgentBacktest` and `SystemLog` tables
4. On completion, agent transitions to BACKTEST_COMPLETE

### Path 2: Claude Code Cloud Task (Optional)

For heavier workloads or when Anthropic infrastructure is preferred:

1. Create a Claude Code Remote Task that clones the repo
2. Task runs `agents/backtesting/tools/pipeline.py` with config
3. Each step POSTs progress to `POST /api/v2/agents/{id}/backtest-progress`
4. The same endpoint handles both local and cloud callbacks

## Wizard Steps (V3)

### Step 1: Channel Selection

- Enter agent name and type (trading/trend)
- Select a Discord connector from active connectors
- Choose a specific channel to monitor
- Optional: add description

### Step 2: Risk Configuration

- Max daily loss percentage (default: 5%)
- Max position size percentage (default: 10%)
- Stop loss percentage (default: 2%)
- Smart hold toggle and buffer

### Step 3: Review & Create

- Summary of all configuration
- Execution info (backtesting runs locally, live trading via Docker worker)
- Click "Create Agent" to start

## Backtesting Pipeline Steps

| Step | Script | Progress | Description |
|------|--------|----------|-------------|
| 1 | transform.py | 15% | Ingest and parse Discord messages into structured signals |
| 2 | enrich.py | 30% | Add market data (price, volume, indicators) to each signal |
| 3 | preprocess.py | 35% | Feature engineering for ML models |
| 4 | train_xgboost.py | 45% | Train XGBoost classifier |
| 5 | train_lightgbm.py | 50% | Train LightGBM classifier |
| 6 | train_catboost.py | 55% | Train CatBoost classifier |
| 7 | train_rf.py | 58% | Train Random Forest classifier |
| 8 | evaluate_models.py | 70% | Compare models, select best, compute metrics |
| 9 | discover_patterns.py | 80% | Find recurring profitable patterns in trade data |
| 10 | build_explainability.py | 85% | SHAP analysis and feature importance |
| 11 | create_live_agent.py | 95% | Build live agent manifest from backtest results |

## Database Schema

### Agent Table

Key fields for lifecycle management:

- `status`: CREATED → BACKTESTING → BACKTEST_COMPLETE → APPROVED/PAPER → RUNNING → PAUSED
- `worker_status`: STOPPED | STARTING | RUNNING | ERROR (Docker worker state)
- `worker_container_id`: Docker container ID for live trading
- `phoenix_api_key`: Unique API key for agent callbacks
- `manifest`: JSONB with full agent configuration (rules, modes, risk, models)

### AgentBacktest Table

- `status`: RUNNING → COMPLETED/FAILED
- `current_step`: Name of the currently executing step
- `progress_pct`: 0-100 integer
- `metrics`: JSONB with backtest results (trades, win rate, patterns, etc.)

## HTTP Callback Endpoints

Used by both local task_runner and Claude Code Cloud Tasks:

- `POST /api/v2/agents/{id}/backtest-progress` — step-by-step progress updates
- `POST /api/v2/agents/{id}/live-trades` — report executed trades
- `POST /api/v2/agents/{id}/metrics` — report performance metrics
- `POST /api/v2/agents/{id}/heartbeat` — keep-alive from running agents

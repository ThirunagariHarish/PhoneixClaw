# How Phoenix Trading Bot Works

A plain-English walkthrough of what happens from "I have a Discord channel I want to backtest" to "an autonomous Claude agent is taking trades in Robinhood and reporting to me via WhatsApp."

---

## The Core Idea

Phoenix is a **multi-agent trading platform** where every agent is a **Claude Code session** running in a sandboxed working directory. Agents are not Python daemons or microservices — they are real Claude Code processes that read instructions from a `CLAUDE.md` file and execute Python tools to do work.

There are six agent types:

| Agent Type | Purpose | Source |
|---|---|---|
| **Backtesting Agent** | Pulls Discord history, trains ML models, discovers patterns | `agents/backtesting/` |
| **Analyst Agent** | Live trading from Discord signals | `agents/templates/live-trader-v1/` |
| **Position Monitor Sub-Agent** | One per open position; finds optimal exit | `agents/templates/position-monitor-agent/` |
| **Unusual Whales Agent** | Monitors options flow + dark pool prints | `agents/templates/unusual-whales-agent/` |
| **Social Sentiment Agent** | Reddit + Twitter signal scanning | `agents/templates/social-sentiment-agent/` |
| **Strategy Agent** | Rule-based strategies (EMA crossover, 52w levels) | `agents/templates/strategy-agent/` |
| **Supervisor Agent** | Nightly AutoResearch — analyzes performance, proposes improvements | `agents/templates/supervisor-agent/` |

---

## End-to-End: From Channel to Live Trades

### Step 1 — User creates an agent in the dashboard

```
Dashboard → "+ New Agent" → 3-step wizard:
  1. Pick a connector (Discord channel)
  2. Set risk parameters (stop loss %, max position %, daily loss limit)
  3. Review and create
```

This sends a `POST /api/v2/agents` request to the FastAPI backend with the channel ID, risk config, and selected connector.

### Step 2 — API spawns a backtesting Claude session

In `apps/api/src/routes/agents.py::create_agent()`:

1. Inserts a new `Agent` row (status = `BACKTESTING`)
2. Inserts a new `AgentBacktest` row (status = `RUNNING`)
3. Calls `gateway.create_backtester(agent_id, backtest_id, config)`

In `apps/api/src/services/agent_gateway.py::create_backtester()`:

1. **Singleton check** — only one backtest runs per agent at a time (Phase 1.1)
2. Computes the next version number → creates `data/backtest_{agent_id}/output/v{N}/` (so re-runs don't overwrite previous results)
3. Writes `config.json` with the channel info, Discord token, risk params
4. Spawns a **Claude Code session** via `claude_agent_sdk.query()` with that working directory and the backtesting prompt

### Step 3 — Claude Code agent runs the 12-step pipeline

The backtesting agent reads `agents/backtesting/CLAUDE.md` and executes:

1. **Transform** — pull Discord history, parse trade signals
2. **Enrich** — add ~200 market features per trade (price action, technicals, volume, sentiment, options flow)
3. **Text embeddings** — sentence-transformer vectors for Discord messages
4. **Preprocess** — train/val/test split
5. **Model selection** — `model_selector.py` picks optimal models based on dataset size (LightGBM/CatBoost only for small data, adds LSTM/TCN for larger)
6. **Train selected models** sequentially (memory-constrained)
7. **Evaluate** → pick best model
8. **Explainability** → top features
9. **Pattern discovery** → multi-condition trading rules
10. **LLM strategy analysis** → narrative interpretation of patterns
11. **Create live agent** → builds `manifest.json` with rules, character, models
12. Reports `status=COMPLETED` to Phoenix API

After each step, the agent calls back to `POST /api/v2/agents/{id}/backtest-progress` so the dashboard shows progress in real time.

### Step 4 — Backtest completes → user reviews and approves

When the backtest finishes:

1. `_auto_create_analyst()` (in agent_gateway) loads the manifest from `output/v{N}/live_agent/manifest.json` into the Agent record
2. Agent status becomes `BACKTEST_COMPLETE`
3. Dashboard shows the metrics (win rate, Sharpe, drawdown, patterns)
4. User reviews and clicks **Approve**
5. `POST /api/v2/agents/{id}/approve` runs:
   - Stores Robinhood credentials (decrypted from connector)
   - Sets agent status to `APPROVED` (live) or `PAPER` (paper trading)
   - **Auto-spawns the live analyst Claude session immediately** (Phase 1.2)

### Step 5 — Live analyst agent runs

The analyst agent reads its rendered `CLAUDE.md` (built from a Jinja2 template with the agent's character and rules baked in) and starts the live loop:

1. Starts the **Discord listener** (`tools/discord_listener.py`) — watches the configured channel
2. For each new message → runs `decision_engine.py`:
   - Parse signal (extract ticker, direction, price)
   - Enrich with current market data
   - Run inference using the trained model
   - Risk check (3-layer chain)
   - Technical analysis confirmation
   - **If confidence < threshold → add to watchlist** (Phase 1.5)
   - **If paper mode → add to Robinhood watchlist + record simulated entry**
   - **If live mode → place real order via robinhood_mcp**
3. After successful trade → calls `POST /api/v2/agents/{id}/spawn-position-agent`

### Step 6 — Position sub-agent spawns

For each open position, a NEW Claude Code session spawns in `data/live_agents/{agent_id}/positions/{ticker}_{timestamp}/`:

1. Reads `position.json` (its assigned position)
2. Runs `exit_monitor.py` in a loop:
   - First 5 min: check every 30s
   - Then: check every 2 min (or 30s if urgency >= 50)
3. Each check runs `exit_decision.py` which combines:
   - Technical analysis (`ta_check.py` — RSI, MACD, BB, S/R)
   - MAG-7 correlation (`mag7_correlation.py`)
   - Discord sell signal detection (`discord_sell_signal.py`)
   - Risk levels (stop loss, take profit)
4. Action: HOLD / PARTIAL_EXIT / FULL_EXIT based on combined urgency score
5. On full exit → reports to Phoenix → calls `POST /api/v2/agents/{session_id}/terminate` → self-terminates

### Step 7 — Inter-agent knowledge sharing

Agents share knowledge via `POST /api/v2/agent-messages`:

- Unusual Whales agent broadcasts unusual flow alerts → analysts factor them in
- Discord analyst broadcasts a sell signal → position monitors of that ticker raise exit urgency
- Morning routine triggers all agents to share their pre-market research

Each agent runs `tools/agent_comms.py --get-pending` periodically to read new messages.

### Step 8 — Notifications

Trade events fire WhatsApp notifications via `apps/api/src/services/notification_dispatcher.py`:

- Agent wakes up at 9 AM ET → "Good morning! {agent} starting morning research"
- Trade entry → "TRADE: {agent} BUY AAPL @ $185 x10. Reason: ..."
- Trade exit → "CLOSED: AAPL @ $192. P&L: +3.8%. Reason: ..."

User can reply via WhatsApp with `@agent_name <instruction>` → webhook routes to `gateway.send_task()` which queues the instruction in the agent's `pending_tasks.json`.

### Step 9 — Nightly AutoResearch (Supervisor Agent)

At 4:30 PM ET, a Claude Code cron triggers `POST /api/v2/agents/supervisor/run`:

1. Collects today's data from all agents
2. Analyzes performance per agent and per pattern
3. Proposes improvements (raise confidence threshold, tighten stops, etc.)
4. Mini-backtests each proposal on last 30 days
5. **Stages passing improvements as `pending_improvements`** (does NOT apply directly)
6. User reviews on dashboard → approve or reject

---

## Database Schema (Key Tables)

| Table | Purpose |
|---|---|
| `agents` | Master agent records (status, manifest, model_type, pending_improvements) |
| `agent_backtests` | Backtest runs with versioning, metrics, model_selection |
| `agent_sessions` | Every Claude Code session (parent_agent_id for sub-agents, position_ticker, session_role) |
| `agent_trades` | Live trades with decision_status (accepted/rejected/paper/watchlist) |
| `agent_messages` | Inter-agent knowledge sharing |
| `agent_logs` | Per-agent log entries |
| `system_logs` | System-wide log entries |
| `notifications` | WhatsApp/dashboard notifications with event_type and channels_sent |
| `watchlist` | Paper trading positions tracked for simulated P&L |
| `connectors` | Discord/Reddit/Twitter/UW credentials |
| `trading_accounts` | Robinhood broker accounts |

---

## Where Data Lives on Disk

Each agent has a working directory under `data/`:

```
data/
├── backtest_{agent_id}/
│   ├── config.json                 # Top-level config
│   ├── latest.json                 # Pointer to latest version
│   └── output/
│       ├── v1/                     # First backtest run
│       ├── v2/                     # Second re-run
│       │   ├── config.json
│       │   ├── transformed.parquet
│       │   ├── enriched.parquet
│       │   ├── price_cache/        # Cached yfinance data
│       │   ├── models/             # Trained models
│       │   ├── model_selection.json
│       │   ├── patterns.json
│       │   ├── explainability.json
│       │   └── live_agent/
│       │       └── manifest.json   # Built live agent config
│       └── v3/                     # Latest run
│
├── live_agents/
│   └── {agent_id}/
│       ├── CLAUDE.md               # Rendered live agent instructions
│       ├── config.json
│       ├── tools/                  # Inherited live-trader tools
│       ├── skills/                 # Markdown skill files
│       ├── models/                 # Copied trained models
│       ├── pending_tasks.json      # User instructions queued by send_task
│       ├── positions.json
│       ├── paper_trades.json       # Paper mode portfolio
│       ├── watchlist.json          # Low-confidence signals
│       └── positions/              # Sub-agent working dirs
│           └── AAPL_20260406_143000/
│               ├── CLAUDE.md
│               ├── position.json
│               ├── tools/
│               └── exit_check_*.json
│
└── supervisor/
    └── 20260406/                   # One subdir per nightly run
        ├── CLAUDE.md
        ├── tools/
        ├── daily_data.json
        ├── analysis.json
        ├── improvements.json
        └── results.json
```

---

## Key API Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /api/v2/agents` | Create agent + start backtest |
| `POST /api/v2/agents/{id}/approve` | Approve backtest → auto-spawn live agent |
| `POST /api/v2/agents/{id}/spawn-position-agent` | Spawn position monitor sub-agent |
| `POST /api/v2/agents/{id}/terminate` | Self-terminate (called by sub-agents) |
| `GET /api/v2/agents/{id}/position-agents` | List active sub-agents for an analyst |
| `GET /api/v2/agents/{id}/paper-portfolio` | Paper mode positions + simulated P&L |
| `GET /api/v2/agents/{id}/runtime-info` | Host, PID, working dir, uptime, memory |
| `GET /api/v2/agents/{id}/activity-feed` | Unified logs + trades + messages |
| `GET /api/v2/agents/graph` | Agent topology data for visualization |
| `POST /api/v2/agents/{id}/instruct` | Send instruction to running agent |
| `POST /api/v2/agents/morning-briefing` | Trigger morning routine (cron) |
| `POST /api/v2/agents/supervisor/run` | Trigger AutoResearch supervisor (cron) |
| `GET /api/v2/agent-knowledge/{topic}` | Query knowledge from all agents on a topic |
| `POST /api/v2/agent-messages` | Send/broadcast inter-agent message |
| `POST /webhook/whatsapp` | Incoming WhatsApp message handler |

---

## Cron Schedule

| Time (ET) | Job | Endpoint |
|---|---|---|
| 9:00 AM | Morning routine | `POST /api/v2/agents/morning-briefing` |
| 9:30 AM | Market open | (analysts wake automatically) |
| 4:00 PM | Market close | (positions stop monitoring) |
| 4:30 PM | EOD watchlist review | (per-agent `watchlist_review.md` skill) |
| 4:30 PM | AutoResearch supervisor | `POST /api/v2/agents/supervisor/run` |

These are configured via Claude Code cron (the `/schedule` skill).

---

## Summary

**Phoenix is not "code that trades" — it's an army of Claude Code agents that read instructions, run Python tools, share knowledge, and self-improve.**

The Python services (FastAPI, Postgres, Redis) exist only to:
1. Spawn and manage agent sessions
2. Persist state and logs
3. Route messages between agents
4. Serve the dashboard
5. Dispatch notifications

The actual *intelligence* lives in the agents' CLAUDE.md files and the tools they invoke.

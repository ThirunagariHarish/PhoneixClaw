# Project Phoenix v2 — Product Requirements Document

**Version:** 2.1.0
**Date:** March 3, 2026
**Status:** SUPERSEDED (2026-04-18)

**NOTE:** This PRD contains legacy OpenClaw-based architecture. As of Phase F (April 2026), Phoenix uses Claude Code SDK runtime. OpenClaw references in this document are historical. See `docs/prd/phase-f-openclaw-removal.md` and `docs/architecture/` for current architecture.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Dashboard Tabs](#3-dashboard-tabs)
4. [Agent Integration](#4-agent-integration) (formerly OpenClaw Integration — deprecated)
5. [Agent Lifecycle](#5-agent-lifecycle)
6. [Trading Agent Architecture](#6-trading-agent-architecture)
7. [Strategy Agent Architecture](#7-strategy-agent-architecture)
8. [Position Monitoring](#8-position-monitoring)
9. [Dev Agent & Reinforcement Learning](#9-dev-agent--reinforcement-learning)
10. [Agent-to-Agent Communication](#10-agent-to-agent-communication)
11. [Task Board & Automations](#11-task-board--automations)
12. [Skill Catalog & Skill Development Framework](#12-skill-catalog--skill-development-framework)
13. [Connector Framework](#13-connector-framework)
14. [Backtesting Engine](#14-backtesting-engine)
15. [Tech Stack & Reusable Components](#15-tech-stack--reusable-components)
16. [Data Model](#16-data-model)
17. [Deployment & Code Cleanup](#17-deployment--code-cleanup)
18. [Risk & Trade Execution Architecture](#18-risk--trade-execution-architecture)
19. [Appendix](#19-appendix)

---

## 1. Executive Summary

### 1.1 Vision

Project Phoenix v2 is an autonomous multi-agent trading platform that uses a custom web dashboard as a centralized control plane to orchestrate multiple OpenClaw instances. Each OpenClaw instance runs specialized AI agents that handle data ingestion, trade signal evaluation, backtesting, strategy execution, risk management, and position monitoring. The platform follows the principle that **LLMs should be strategy engineers, not discretionary traders** — every agent must prove its worth through backtesting before touching real capital.

### 1.2 Goals

- **Centralized Control, Distributed Intelligence**: A single dashboard manages all agents across multiple OpenClaw instances running on separate VPS/local machines.
- **Agent-First Architecture**: Every trading decision flows through an AI agent that has been backtested and approved. No agent trades live without passing through the full lifecycle (backtest → review → paper → live).
- **Signal-Agnostic Ingestion**: Consume signals from Discord channels, Reddit, Twitter/X, Unusual Whales, news APIs, and custom data sources.
- **Robust Execution**: Agents never place orders directly. All trades flow through a queue-based execution pipeline with a dedicated broker execution service for reliability and auditability.
- **Paired Agent Architecture**: Every trading agent is paired with a monitoring agent that watches positions and manages exits.
- **Skill Reuse Without Duplication**: A centralized skill repository syncs to all OpenClaw instances, so skills are authored once and available everywhere.
- **Self-Improving System**: A Dev Agent with reinforcement learning continuously monitors all agents, detects failures, auto-fixes code, tunes parameters, and evolves strategies over time.
- **Agent Collaboration**: Agents communicate with each other across instances to confirm signals, share analysis, and increase trade probability through consensus.
- **Bidirectional Communication**: Users interact with agents through Discord, Telegram, and WhatsApp — both for receiving alerts and for issuing commands/tasks.
- **Trading Firm of Agents**: Agents operate as a virtual trading firm with specialized roles (Day Trader, Technical Analyst, Risk Analyzer, Market Research Analyst) that can create and manage their own tasks.
- **Mobile-Friendly**: The entire dashboard is responsive and usable on mobile devices with PWA capability.

### 1.3 Key Differentiators

| Aspect | Traditional Bots | Phoenix v2 |
|---|---|---|
| Decision making | Hard-coded rules or raw LLM "vibes" | Backtested, approved AI agents with structured evaluation |
| Architecture | Single monolith | Distributed OpenClaw instances with specialized agent roles |
| Trade execution | Direct broker calls from bot | Queue-based pipeline with dedicated execution service |
| Position management | Basic stop-loss | Dedicated monitoring agent per trading agent |
| Strategy development | Manual coding | AI-engineered strategies with automated backtesting |
| Skill management | Per-bot configuration | Centralized skill repo synced to all instances |
| Self-improvement | None — manual intervention | Dev Agent with RL continuously monitors, fixes, and evolves agents |
| Agent collaboration | Isolated bots | Agents talk to each other to confirm signals and build consensus |
| User interaction | Dashboard only | Bidirectional via Discord, Telegram, WhatsApp, and dashboard |
| Code generation | Human-written only | Agents write Python code, build predictive models, run calculations |

### 1.4 Non-Goals (v2 Scope)

- Mobile native app (responsive web with PWA — not native iOS/Android)
- High-frequency trading (sub-second latency)
- Cryptocurrency DEX execution (CEX and traditional brokers only)

---

## 2. System Architecture

### 2.1 High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                         CONTROL PLANE                               │
│                                                                     │
│  ┌──────────────┐    ┌──────────────┐    ┌─────────────────────┐   │
│  │  Custom Web  │◄──►│  Backend API │◄──►│  PostgreSQL + Redis │   │
│  │  Dashboard   │    │  (FastAPI)   │    │  (App DB + Cache)   │   │
│  │  (React/TS)  │    └──────┬───────┘    └─────────────────────┘   │
│  └──────────────┘           │                                       │
│                    ┌────────┴────────┐                               │
│                    │  Job Queue      │                               │
│                    │  (Redis+BullMQ) │                               │
│                    └────────┬────────┘                               │
│                             │                                        │
│                    ┌────────┴────────┐                               │
│                    │  Orchestrator   │                               │
│                    │  Worker         │                               │
│                    └────────┬────────┘                               │
│                             │                                        │
│                    ┌────────┴────────┐                               │
│                    │  Event Bus      │                               │
│                    │  (Redis Streams │                               │
│                    │   / NATS)       │                               │
│                    └────────┬────────┘                               │
└─────────────────────────────┼───────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│  OpenClaw       │ │  OpenClaw       │ │  OpenClaw       │
│  Instance A     │ │  Instance B     │ │  Instance C/D   │
│  Strategy Lab   │ │  Data/Research  │ │  Risk / Trading │
│  (VPS-1)        │ │  (VPS-2)        │ │  (VPS-3)        │
└─────────────────┘ └─────────────────┘ └─────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    SHARED SERVICES                           │
│                                                             │
│  ┌──────────┐  ┌───────────────┐  ┌──────────────────────┐ │
│  │ Artifact │  │ Market Data   │  │ Broker Execution     │ │
│  │ Store    │  │ Cache         │  │ Service              │ │
│  │ (S3/     │  │ (Parquet/     │  │ (Alpaca/IBKR/        │ │
│  │  MinIO)  │  │  TimescaleDB) │  │  Robinhood)          │ │
│  └──────────┘  └───────────────┘  └──────────────────────┘ │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Observability: Central Logs + Metrics + Dashboard   │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 OpenClaw Instance Topology

Four logical OpenClaw instances, deployable across 1-N physical machines:

| Instance | Role | Agents | Tool Allowlist |
|---|---|---|---|
| **A: Strategy Lab** | Build, test, and validate strategies | Strategy Builder, Code Generator, Unit Test Fixer, Backtest Analyst | `write-file`, `run-tests`, `run-backtest`, `read-file` |
| **B: Data & Research** | Fetch and cache market data, interpret news/sentiment | Data Planner, Data Fetcher, News/Sentiment Analyst | `get-data`, `cache-data`, `get-news`, `browse-web` |
| **C: Promotion & Risk** | Rank strategies, enforce risk limits, manage deployments | Strategy Selector, Risk Supervisor, Deployment Manager | `score`, `gate`, `deploy`, `kill-switch` |
| **D: Live Trading Ops** | Execute trades and monitor positions | Live Trader (Stocks), Live Trader (Options), Trade Monitor, Incident/Recovery | `place-order`, `cancel`, `get-positions`, `get-quotes` |

### 2.3 Communication Flow

```
Dashboard API
     │
     ▼
Job Queue (Redis + BullMQ)
     │
     ▼
Orchestrator Worker (state machine with retries)
     │
     ▼
Event Bus (Redis Streams / NATS)
     │
     ├──► OpenClaw Instance A (Strategy Lab)
     ├──► OpenClaw Instance B (Data & Research)
     ├──► OpenClaw Instance C (Promotion & Risk)
     └──► OpenClaw Instance D (Live Trading Ops)
            │
            ▼
      Broker Execution Service
            │
            ▼
      Orders & Positions Store
```

The Event Bus is the backbone. Every OpenClaw instance publishes status updates, trade signals, and position changes back to the bus. The Orchestrator Worker consumes these events, updates the database, and pushes real-time updates to the dashboard via WebSocket/SSE.

### 2.4 Intelligence-in-OpenClaw Principle

All intelligence lives in OpenClaw agents. The dashboard is a control plane and display layer — it does not make trading decisions, run strategies, or execute analysis. The backend API orchestrates jobs, manages state, and relays data. OpenClaw instances are the compute nodes where all AI reasoning, evaluation, code generation, model training, and decision-making happen.

This separation means:
- Adding new intelligence = adding/updating OpenClaw agents and skills (no backend code changes)
- The dashboard can be rebuilt or replaced without affecting trading operations
- OpenClaw instances can operate independently if the dashboard goes down (agents continue trading, queuing results)

### 2.5 1-Minute Heartbeat Orchestration

The dashboard stays current through a 1-minute heartbeat cycle:

```
Every 60 seconds:
    │
    ├─ Backend polls each OpenClaw instance Bridge Service:
    │   GET /heartbeat
    │   Response: {
    │     agents: [{ id, status, current_task, pnl_today, positions, last_trade }],
    │     instance_health: { cpu, memory, uptime },
    │     recent_events: [{ type, agent_id, data, timestamp }]
    │   }
    │
    ├─ Backend aggregates all instance responses
    │
    ├─ Updates database (agent statuses, positions, metrics)
    │
    └─ Pushes delta to dashboard via WebSocket
        → Frontend updates all visible components in-place
```

For time-critical updates (trade fills, position changes, alerts), the Event Bus provides sub-second push via WebSocket/SSE in addition to the heartbeat cycle.

### 2.6 Why Queue-Based Execution (Not Direct)

Agents push trade intents to the execution queue rather than calling broker APIs directly. This is the recommended architecture for the following reasons:

1. **Reliability**: If the broker API is down, trades queue up and retry. Direct calls from an agent would fail silently or require complex retry logic inside the LLM context.
2. **Auditability**: Every trade intent is logged before execution. The execution service records the full lifecycle: intent → validation → order → fill → confirmation.
3. **Rate limiting**: Broker APIs have rate limits. A central execution service can throttle and batch orders across all agents.
4. **Risk checks**: The execution service applies final risk checks (max position size, daily loss limit, circuit breakers) before placing orders. This is a hard safety net that cannot be bypassed by any agent.
5. **Deduplication**: Prevents duplicate orders if an agent retries or if two agents produce the same signal.

---

## 3. Dashboard Tabs

The dashboard is the single pane of glass for the entire platform. It has 10 primary tabs, each serving a distinct function. Tab visibility is controlled by RBAC — not all users see all tabs.

### 3.1 Trades Tab

**Purpose**: Shows every trade signal that has moved through the pipeline, regardless of which agent or account generated it. This is the "message log" of the trading system.

**Key Views**:

| Column | Description |
|---|---|
| Timestamp | When the signal was generated |
| Agent | Which trading/strategy agent produced the signal |
| Ticker | Symbol (e.g., AAPL, SPY 450C 03/15) |
| Action | BUY / SELL / CLOSE |
| Source | Data source that triggered the signal (e.g., Discord #options-flow, Reddit r/wallstreetbets, Strategy Heartbeat) |
| Status | `queued` → `evaluating` → `approved` → `executing` → `filled` / `rejected` / `failed` |
| Entry Price | Price at signal generation |
| Fill Price | Actual execution price |
| Account | Trading account assigned |
| PnL | Realized PnL (if closed) |

**Filters**: By agent, by account, by status, by ticker, by date range, by source.

**Real-Time**: New trades stream in via WebSocket. Status transitions animate in place.

**UI Components**:
- Sortable data table (reuse existing `Table` primitive with `TanStack Table`)
- Status badge with color coding: green (filled), yellow (evaluating/queued), red (rejected/failed), blue (executing)
- Expandable row showing full trade detail: agent reasoning, evaluation logs, execution timestamps, broker response

### 3.2 Positions Tab

**Purpose**: Account-centric view of all open and recently closed positions. This tab answers "what is each trading account holding right now?"

**Key Views**:

**Open Positions Table**:

| Column | Description |
|---|---|
| Account | Trading account name + mode (paper/live) |
| Ticker | Symbol |
| Side | LONG / SHORT |
| Qty | Number of shares/contracts |
| Entry Price | Average entry |
| Current Price | Real-time (polling every 5s) |
| Unrealized PnL | Current profit/loss |
| PnL % | Percentage change |
| Agent | Which agent opened this position |
| Monitor Agent | Which monitoring agent is watching this |
| Stop Loss | Current stop level |
| Time Held | Duration since entry |
| Actions | Manual close button, adjust stop |

**Closed Positions Table** (toggleable):
- Same columns plus Exit Price, Realized PnL, Exit Reason (stop-loss, take-profit, agent decision, analyst close, EOD)

**Account Summary Cards** (top of page):
- Total account value
- Day PnL (dollar + percentage)
- Open positions count
- Buying power remaining
- Win rate (today / all-time)

**UI Components**:
- Flex cards for account summaries (reuse `Card` primitive)
- Data table with real-time price updates
- Color-coded PnL (green positive, red negative)
- Sparkline per position showing intraday price movement (Recharts `AreaChart`)

### 3.3 Performance Tab

**Purpose**: Deep analytics across all accounts, agents, and strategies. A long scrollable page of tables and metrics.

**Section 1 — Account Performance**:

| Metric | Description |
|---|---|
| Total PnL | By account, sortable |
| Win Rate | Percentage of profitable trades |
| Sharpe Ratio | Risk-adjusted return |
| Max Drawdown | Largest peak-to-trough decline |
| Profit Factor | Gross profit / gross loss |
| Average Win / Average Loss | Dollar amounts |
| Best Day / Worst Day | Calendar view option |

**Section 2 — Top/Bottom Agent Performers**:
- Table: Top 10 agents by PnL (all time, this month, this week, today)
- Table: Bottom 10 agents by PnL
- Per-agent metrics: trade count, win rate, average hold time, Sharpe, max drawdown

**Section 3 — Agent-Account Matrix**:
- Cross-reference table showing which agents are assigned to which accounts and their performance in each
- Heatmap visualization: rows = agents, columns = accounts, cell color = PnL intensity

**Section 4 — Source Performance**:
- Which data sources (Discord channels, Reddit subs, etc.) produce the most profitable signals
- Table: source name, signal count, conversion rate (signal → trade), average PnL per signal

**Section 5 — Time-Based Analysis**:
- PnL by hour of day (bar chart)
- PnL by day of week (bar chart)
- Cumulative equity curve (line chart, Recharts `LineChart`)
- Monthly returns grid (calendar heatmap)

**Section 6 — Strategy Performance** (for strategy agents):
- Strategy name, backtest Sharpe, live Sharpe, divergence score
- Comparison: backtest results vs. live results

**UI Components**:
- Multiple `Card` sections with embedded `Table` components
- Recharts for all charts (AreaChart, BarChart, LineChart)
- Toggle between time ranges (today / week / month / YTD / all-time)
- Export to CSV button per table

### 3.4 Agents Tab (Trading Agents)

**Purpose**: Create, configure, monitor, and manage OpenClaw trading agents. This is the primary agent management interface.

**3.4.1 Agent List View**

The default view shows all trading agents as data-rich flex cards in a responsive grid (3-4 per row on desktop, 1 on mobile).

**Each Agent Card Displays**:
- Agent name + status badge (`backtesting` / `pending_review` / `paper_trading` / `live` / `paused` / `error`)
- Data source (e.g., "Discord: #swing-trades @TraderX")
- Current PnL (total + today)
- Trade count (total / today)
- Win rate
- OpenClaw instance it's running on
- Last activity timestamp
- Sparkline of recent PnL (last 7 days)

**Actions on Card**:
- Click → Agent Detail Page
- Quick actions: Pause / Resume / Stop / Assign Account

**"New Agent" Button** (top right):
Opens a multi-step creation wizard:

**Step 1 — Configuration**:
- Agent name
- Data source selection (dropdown of configured connectors — see Connectors Tab)
- For Discord: select server → select channel(s)
- For Reddit: select subreddit(s)
- For Unusual Whales: select flow type (options flow, dark pool, etc.)
- Agent description / trading thesis

**Step 2 — Skills Assignment**:
- Multi-select from available skills (see Skill Catalog, Section 9)
- Required skills auto-selected based on data source type
- Optional skills for enhancement (e.g., sentiment analysis, options chain analysis)

**Step 3 — OpenClaw Instance**:
- Select which OpenClaw instance to deploy to
- Shows current load per instance (agent count, CPU, memory)
- "Auto-select" option picks the least loaded instance

**Step 4 — Risk Parameters**:
- Max position size (dollars or shares)
- Max concurrent positions
- Stop-loss percentage (default: 20%)
- Take-profit target (optional)
- Daily loss limit
- Allowed trading hours

**Step 5 — Review & Create**:
- Summary of all configuration
- "Create Agent" button → agent enters `backtesting` state

**3.4.2 Agent Detail Page**

When you click an agent card, you see the full agent detail with two main tabs:

**Backtesting Tab**:
- Status: progress bar showing backtest completion
- Task log: scrollable log of what the agent is doing in real-time (streamed from OpenClaw)
  - "Fetching historical messages from Discord #options-flow (2024-01-01 to 2026-03-01)..."
  - "Evaluating message: 'AAPL 180C 03/15 looking strong' — Signal: BUY..."
  - "Simulating entry at $3.20, exit at stop-loss $2.56 — Loss: -$0.64 per contract..."
- Summary metrics once complete:
  - Total signals evaluated
  - Trades taken vs. passed
  - Total PnL
  - Win rate
  - Sharpe ratio
  - Max drawdown
  - Equity curve chart
- Detailed trades table: every simulated trade with entry/exit/PnL/reasoning
- **"Approve for Paper Trading"** button (only visible after backtest completes)
- **"Reject & Reconfigure"** button

**Live/Paper Tab**:
- Real-time activity feed (what the agent is doing right now)
- Current positions held by this agent
- Today's trades
- Cumulative PnL chart
- Agent logs (evaluation reasoning for each signal)

**3.4.3 Agent Card Design** (inspired by the Agent Overview screenshot)

```
┌─────────────────────────────────────┐
│  Echo ●                    PnL      │
│  Discord: #options-flow    +43.061  │
│  Instance: OC-Live-1       SOL      │
│  Latency: 20ms                      │
│                                     │
│  ┌─────────┬──────┬───────┬──────┐  │
│  │Contract │ Size │ Entry │ PnL  │  │
│  ├─────────┼──────┼───────┼──────┤  │
│  │AAPL 180C│ 1.0  │ 3.20  │ 0.8  │  │
│  │SPY 450P │ 1.0  │ 2.10  │-0.3  │  │
│  │NVDA 900C│ 1.5  │ 8.00  │ 1.2  │  │
│  └─────────┴──────┴───────┴──────┘  │
│                                     │
│  Trades: 47  │  Win Rate: 62%       │
└─────────────────────────────────────┘
```

### 3.5 Strategy Agents Tab

**Purpose**: Create and manage rule-based strategy agents. Unlike trading agents (which react to external signals), strategy agents follow predefined algorithmic strategies and run on heartbeat schedules.

**3.5.1 Strategy Library**

A list of 30-40 pre-built strategy templates:

| Category | Strategies |
|---|---|
| Momentum | RSI Reversal, MACD Crossover, Breakout Momentum, 52-Week High Breakout, Relative Strength |
| Mean Reversion | Bollinger Band Bounce, RSI Oversold/Overbought, VWAP Reversion, Gap Fill |
| Trend Following | Dual Moving Average, ADX Trend, Ichimoku Cloud, Supertrend |
| Options | Iron Condor Weekly, Covered Call, Wheel Strategy, Straddle on Earnings, 0DTE Scalp |
| Volume | Volume Spike, OBV Divergence, Relative Volume Breakout, VWAP Cross |
| Sentiment | Put/Call Ratio Extreme, VIX Mean Reversion, Fear & Greed Contrarian |
| Multi-Factor | Momentum + Value, Quality + Low Vol, Sector Rotation, Pairs Trading |
| Intraday | Opening Range Breakout, First Pullback, VWAP Scalp, Pre-Market Gap |
| Event-Driven | Earnings Drift, FDA Approval, Dividend Capture, Index Rebalance |

**3.5.2 Strategy Agent Creation**

**Step 1 — Select Strategy**: Pick from library or create custom.

**Step 2 — Configure Parameters**:
- Instrument universe (e.g., S&P 500, NASDAQ 100, specific tickers)
- Timeframe (1m, 5m, 15m, 1h, daily)
- Strategy-specific parameters (e.g., RSI period=14, overbought=70, oversold=30)
- Position sizing rules
- Entry/exit conditions

**Step 3 — Backtesting** (automatic):
- Agent immediately begins backtesting on creation
- Pulls historical data for the configured instruments and timeframe
- Runs the strategy against 2 years of data (configurable)
- Generates full performance report

**Step 4 — Review**:
- If backtest results are poor (negative PnL, Sharpe < 0.5), agent is flagged
- User reviews metrics and decides: approve for paper, reject, or reconfigure

**Step 5 — Paper/Live Assignment**:
- Assign to paper trading account
- After paper trading period, promote to live

**3.5.3 Strategy Agent Runtime**

Strategy agents differ from trading agents in execution model:

- **Heartbeat-driven**: Agent runs on a cron schedule (e.g., every 5 minutes during market hours)
- **Self-contained**: Agent pulls its own data, runs strategy logic, and pushes trade signals to the execution queue
- **No external trigger**: Does not wait for Discord messages or external signals
- **Continuous data logging**: Writes strategy state, signals, and decisions to a shared database/file that the dashboard reads

```
HEARTBEAT.md (for a strategy agent):

## Active Strategy: RSI Reversal on SPY
- Every 5 minutes during 9:30 AM - 3:50 PM ET (weekdays):
  1. Fetch latest SPY 5-minute bars
  2. Calculate RSI(14)
  3. If RSI < 30 and no open position: generate BUY signal
  4. If RSI > 70 and holding: generate SELL signal
  5. Log decision to /workspace/strategy_log.jsonl
  6. If signal generated: POST to execution queue API
- At 3:50 PM: Close all open positions (EOD rule)
```

### 3.6 Connectors Tab

**Purpose**: Configure and manage all external data sources, trading accounts, and API integrations.

**3.6.1 Data Source Connectors**

**Discord**:
- OAuth2 bot token configuration
- Server discovery and selection
- Channel-level configuration (pick specific channels)
- Per-channel agent assignment
- Message format: text messages containing trade ideas, alerts, analysis

**Reddit**:
- API credentials (client ID, secret)
- Subreddit selection (e.g., r/wallstreetbets, r/options, r/stocks)
- Post type filter (new, hot, rising)
- Flair filter
- Keyword filter

**Twitter/X**:
- API bearer token
- Account follows / list monitoring
- Keyword/cashtag tracking ($AAPL, $SPY)
- Filtered stream rules

**Unusual Whales**:
- API key configuration
- Flow type selection:
  - Options flow (sweeps, blocks, splits)
  - Dark pool prints
  - Congressional trades
  - Insider trades
- Filter configuration: min premium, ticker filter, flow type
- WebSocket vs. polling toggle

**News APIs**:
- Finnhub, NewsAPI, Alpha Vantage, Benzinga
- API key per provider
- Keyword/ticker subscription
- Sentiment threshold for alerts

**Custom Webhook**:
- Receive trade signals via HTTP POST
- Configurable payload schema
- Authentication (API key, HMAC)
- Webhook URL provided per connector

**3.6.2 Trading Account Connectors**

**Alpaca** (Primary — recommended):
- API key + secret
- Paper trading: free, $100k default balance, reset anytime
- Live trading: real money execution
- Supports: stocks, options, crypto
- 99.99% uptime, 1.5ms order processing

**Interactive Brokers (IBKR)**:
- TWS API connection (host, port, client ID)
- Paper or live mode
- Supports: stocks, options, futures, forex, bonds
- Requires funded account

**Robinhood** (via robin_stocks):
- Username/password + MFA
- Paper mode: simulated (internal tracking, no Robinhood paper API)
- Live mode: real execution
- Supports: stocks, options, crypto

**Tradier**:
- Access token
- Paper (sandbox) and live environments
- Supports: stocks, options

**UI for Each Connector**:
- Connection status indicator (green/red)
- Last sync timestamp
- Test connection button
- Edit credentials (encrypted at rest)
- Delete connector

### 3.7 Skills & Agents Config Tab

**Purpose**: Two-section page for managing the centralized skill repository and editing agent configurations across all OpenClaw instances.

**3.7.1 Skills Section**

**Skill List**:
- Searchable, filterable grid of all available skills
- Each skill card shows: name, category, description, installed instances, version
- Filter by category: Data, Analysis, Execution, Risk, Monitoring, Utility

**Skill Detail** (click to expand):
- Full description
- Required tools (e.g., `shell`, `browser`, `python`)
- Input parameters
- Output format
- Version history
- Which agents are currently using this skill

**"Add Skill" Flow**:
1. Browse ClawHub marketplace (3000+ community skills)
2. Upload custom SKILL.md
3. Create from template

**Skill Distribution**:
- When a skill is added to the central repository, a sync job pushes it to all connected OpenClaw instances
- Per-instance toggle: enable/disable specific skills per instance
- Conflict resolution: central version wins, with option to pin instance-specific overrides

**How Centralized Skills Work** (avoiding duplication):
```
Central Skill Repository (S3/MinIO or Git repo)
        │
        ├──► Sync Agent on OC Instance A
        │    └──► ~/.openclaw/skills/phoenix/
        │
        ├──► Sync Agent on OC Instance B
        │    └──► ~/.openclaw/skills/phoenix/
        │
        └──► Sync Agent on OC Instance C/D
             └──► ~/.openclaw/skills/phoenix/
```

Each OpenClaw instance has a lightweight sync agent (cron job or file watcher) that pulls from the central repository. Skills are stored in a `phoenix/` subdirectory within each instance's managed skills folder (`~/.openclaw/skills/`). This gives them second-highest precedence (below workspace skills, above bundled skills).

**3.7.2 Agents Config Section**

**Agent Configuration Editor**:
- List of all agents across all OpenClaw instances
- Click to edit any agent's configuration:
  - AGENTS.md content (system prompt, role, goals)
  - SOUL.md content (personality, communication style)
  - TOOLS.md content (allowed tools)
  - MEMORY.md content (long-term knowledge)
  - Assigned skills
  - Heartbeat/cron schedule
  - Risk parameters

**Bulk Operations**:
- Update a skill across all agents that use it
- Change risk parameters for all agents in an instance
- Pause/resume all agents in an instance

### 3.8 Market Command Center Tab

**Purpose**: Full-featured market intelligence dashboard migrated from the existing Phoenix v1 project. Provides 50+ configurable widgets for real-time market monitoring.

**Layout System**:
- `react-grid-layout` with `ResponsiveGridLayout` (12-column grid)
- Responsive breakpoints: lg 1200, md 996, sm 768, xs 480, xxs 0
- Row height 40px, margins 8px, drag-and-drop via `.drag-handle`
- Multiple tabbed canvases (Overview, Day Trading, Options, etc.) — users create/rename/delete/duplicate tabs
- Layouts persisted to localStorage (`mcc-tabs-v2`) and optionally synced to server

**Widget Categories** (carried over from existing `pages/MarketCommandCenter.tsx`):

| Category | Widgets |
|---|---|
| Market Pulse | Fear & Greed Index, VIX, Market Breadth, Market Clock, Ticker Tape, Symbol Info, Trading Session |
| Indices & Performance | Global Indices, Mag 7, Sector Performance, Futures |
| News & Social | Breaking News, Trending Videos, Social Feed, RSS Feed, Top Stories |
| Assets | Crypto, Commodities, Forex, Bond Yields |
| Charts | Market Heatmap, TradingView Chart, Mini Chart, Technical Analysis, Crypto Heatmap, ETF Heatmap |
| Screeners | Stock Screener, Forex Cross Rates, Crypto Screener |
| SPX Day Trading | GEX, Market Internals, VIX Term Structure, Premarket Gaps, SPX Key Levels, Options Flow, Correlations, Volatility Dashboard, Premarket Movers, Day Trade PnL |
| Tools | Position Size Calculator, Risk/Reward, Trading Checklist, Quick Notes, Session Timer, Keyboard Shortcuts |
| Platform | Platform Sentiment, Day Trade PnL |

**Configurable Widgets**: Widgets like TradingView Chart, VIX, Technical Analysis, GEX, Options Flow allow symbol customization via `TickerSearch` component.

### 3.9 Admin & User Management Tab

**Purpose**: Role-based access control, user management, and system audit log. Restricted to admin and manager roles.

**3.9.1 User Management** (carried over from existing `pages/Admin.tsx` and `pages/AccessManagement.tsx`):

**User Table**:
- Email, name, role, status (active/inactive), last login
- Promote/demote admin
- Toggle active/inactive
- Export CSV

**Roles** (5 built-in, extensible with custom):

| Role | Access Level |
|---|---|
| `admin` | Full access to all tabs, settings, kill switch, Dev Dashboard |
| `manager` | All tabs except Dev Dashboard and system config, can approve agents for live |
| `trader` | Trades, Positions, Performance, Agents (view only), Market Command Center |
| `viewer` | Read-only access to Trades, Positions, Performance |
| `custom` | Per-permission granular assignment |

**Permissions** (20 total):

| Category | Permissions |
|---|---|
| Trading | Execute Trades, Approve/Reject Trades, View Trades |
| Positions | View Positions, Close Positions |
| Agents | Create Agents, Edit Agents, Approve for Live, View Agent Logs |
| Data Sources | Manage Data Sources, View Data Sources |
| Accounts | Manage Trading Accounts, View Trading Accounts |
| System | System Configuration, Kill Switch Control, View Dev Dashboard |
| Admin | Manage Users, Access Management, View Audit Log |

**Tab Visibility Control**: Each role defines which dashboard tabs are visible. Similar to AutoRabit's access model — admins configure per-role tab access from a matrix UI.

**3.9.2 API Key Vault**

A secure, centralized location to manage all integration credentials:

| Key Type | Fields |
|---|---|
| Broker (Alpaca) | API Key, API Secret, Base URL, Mode (paper/live) |
| Broker (IBKR) | Host, Port, Client ID |
| Broker (Robinhood) | Username, Password, MFA |
| Unusual Whales | API Key |
| Discord | Bot Token |
| Telegram | Bot Token, Chat ID |
| WhatsApp | Phone Number ID, Access Token, Recipient |
| Reddit | Client ID, Client Secret |
| Twitter/X | Bearer Token |
| News APIs | Finnhub Key, NewsAPI Key, Benzinga Key |
| LLM Providers | Anthropic Key, OpenAI Key, Ollama URL |

**Security**:
- All keys encrypted at rest using Fernet (reuse `shared/crypto/credentials.py`)
- Masked display in UI (last 4 characters visible)
- Test connection button per credential set
- Revoke/rotate with one click
- Last-used timestamp and access log
- Keys never sent to frontend — only a masked preview and status

**3.9.3 Audit Log**

- Chronological log of all admin/system actions
- Entries: timestamp, user, action, target, details
- Actions logged: user role changes, agent approvals, kill switch activations, config changes, Dev Agent auto-fixes, connector modifications
- Filterable by user, action type, date range
- Exportable to CSV

### 3.10 Agent Network Visualization (Admin Panel)

**Purpose**: A visual, interactive graph showing the entire agent network — all OpenClaw instances, agents within each, their statuses, and inter-agent communication flows. Admin-only.

**Implementation**: Built with `@xyflow/react` (already a dependency in the existing project).

**Visualization**:
```
┌─────────────────────────────────┐
│ OpenClaw Instance A (VPS-1)     │
│ ┌────────┐ ┌────────┐          │
│ │Strategy│ │ Code   │          │
│ │Builder │ │  Gen   │          │
│ │  (●)   │ │  (●)   │          │
│ └───┬────┘ └────────┘          │
│     │                           │
│ ┌───▼────┐ ┌────────┐          │
│ │Backtest│ │UnitTest│          │
│ │Analyst │ │ Fixer  │          │
│ │  (●)   │ │  (●)   │          │
│ └────────┘ └────────┘          │
└─────────────────────────────────┘
        ▲  ▼ (Event Bus)
┌─────────────────────────────────┐
│ OpenClaw Instance D (VPS-3)     │
│ ┌────────┐ ┌────────┐          │
│ │ Live   │ │ Trade  │          │
│ │Trader  │◄│Monitor │          │
│ │  (●)   │ │  (●)   │          │
│ └────────┘ └────────┘          │
└─────────────────────────────────┘
```

**Node Types**:
- Instance nodes (containers) showing VPS name, role, health metrics
- Agent nodes within each instance showing name, status color, current task

**Status Colors**:
- Green: active and healthy
- Yellow: backtesting or paper trading
- Red: error or paused
- Gray: stopped or dormant
- Blue: processing a task

**Edge Types**:
- Solid lines: active communication channels between agents
- Dashed lines: configured but idle connections
- Animated edges: real-time message flow

**Interactions**:
- Click any agent node to open its detail panel (logs, positions, config)
- Click any instance node to see instance health, agent list, resource usage
- Hover over edges to see recent messages between agents
- Zoom, pan, and minimap for large agent networks

**Real-Time Updates**: Agent statuses and message flows update via WebSocket, reflecting the 1-minute heartbeat data plus sub-second event bus pushes.

---

## 4. OpenClaw Integration

### 4.1 Instance Management

The dashboard manages OpenClaw instances as first-class entities:

**Registration**:
```json
{
  "instance_id": "oc-strategy-lab-01",
  "name": "Strategy Lab (VPS-1)",
  "host": "10.0.1.10",
  "port": 18790,
  "role": "strategy_lab",
  "agents": [],
  "status": "online",
  "cpu_usage": 45,
  "memory_usage": 2048,
  "max_agents": 20
}
```

**Health Monitoring**:
- Heartbeat ping every 30 seconds
- CPU/memory metrics via system agent
- Agent count and status per instance
- Auto-alert on instance going offline

### 4.2 Agent Creation via Dashboard

When a user creates an agent via the dashboard, the following sequence executes:

```
1. Dashboard → Backend API:
   POST /api/v2/agents
   {
     "name": "Discord Options Trader",
     "type": "trading",
     "data_source": { "type": "discord", "channel_id": "123456" },
     "skills": ["signal_parser", "options_evaluator", "risk_calculator"],
     "instance_id": "oc-live-ops-01",
     "risk_config": { "max_position": 5000, "stop_loss_pct": 20 }
   }

2. Backend API → Job Queue:
   Enqueue job: CREATE_AGENT

3. Orchestrator Worker:
   a. Generate AGENTS.md from template + config
   b. Generate TOOLS.md based on assigned skills
   c. Generate HEARTBEAT.md (if strategy agent)
   d. SSH/API call to target OpenClaw instance
   e. Create agent workspace: ~/.openclaw/agents/<agent_id>/
   f. Write config files to workspace
   g. Register agent in openclaw.json bindings
   h. Start agent process

4. OpenClaw Instance → Event Bus:
   Publish: AGENT_CREATED { agent_id, instance_id, status: "active" }

5. Orchestrator → DB:
   Update agent record: status = "backtesting"
   (Backtest job is auto-enqueued)
```

### 4.3 OpenClaw API Bridge

A lightweight bridge service runs alongside each OpenClaw instance. It exposes a REST API that the Orchestrator can call:

| Endpoint | Method | Description |
|---|---|---|
| `/agents` | GET | List all agents on this instance |
| `/agents` | POST | Create new agent (accepts config files) |
| `/agents/:id` | GET | Agent status, metrics, logs |
| `/agents/:id` | PUT | Update agent configuration |
| `/agents/:id` | DELETE | Remove agent |
| `/agents/:id/pause` | POST | Pause agent execution |
| `/agents/:id/resume` | POST | Resume agent execution |
| `/agents/:id/logs` | GET | Stream agent activity logs |
| `/agents/:id/sessions` | GET | List agent sessions |
| `/skills/sync` | POST | Trigger skill sync from central repo |
| `/health` | GET | Instance health metrics |

### 4.4 Multi-Instance Skill Distribution

```
Central Repository (Git or S3)
         │
    ┌────┴────┐
    │ Webhook │  (on push/update)
    └────┬────┘
         │
    POST /skills/sync to each instance
         │
    ┌────┼────────────┬────────────┐
    ▼    ▼            ▼            ▼
  OC-A  OC-B        OC-C        OC-D
  (pulls latest)   (pulls latest) ...
```

Each instance's sync handler:
1. Pulls the latest skill bundle from the central repo
2. Compares checksums to detect changes
3. Updates `~/.openclaw/skills/phoenix/` directory
4. Restarts affected agents if skill files changed

---

## 5. Agent Lifecycle

Every agent follows a strict lifecycle. No agent touches real capital without passing through all gates.

```
┌──────────┐     ┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────┐
│ CREATED  │────►│ BACKTESTING │────►│PENDING_REVIEW│────►│PAPER_TRADING│────►│ LIVE │
└──────────┘     └─────────────┘     └──────────────┘     └─────────────┘     └──────┘
                        │                    │                    │                │
                        ▼                    ▼                    ▼                ▼
                  ┌──────────┐        ┌──────────┐        ┌──────────┐     ┌──────────┐
                  │  FAILED  │        │ REJECTED │        │  PAUSED  │     │  PAUSED  │
                  └──────────┘        └──────────┘        └──────────┘     └──────────┘
                                           │                                    │
                                           ▼                                    ▼
                                    ┌──────────────┐                     ┌──────────┐
                                    │ RECONFIGURED │                     │ STOPPED  │
                                    │ (back to     │                     └──────────┘
                                    │  BACKTESTING)│
                                    └──────────────┘
```

### 5.1 State Definitions

| State | Description | User Action Required |
|---|---|---|
| `CREATED` | Config written, agent not yet running | None (auto-transitions) |
| `BACKTESTING` | Agent is running against historical data | Wait for completion |
| `FAILED` | Backtest crashed or timed out | Review logs, reconfigure |
| `PENDING_REVIEW` | Backtest complete, awaiting user approval | Approve or reject |
| `REJECTED` | User rejected backtest results | Reconfigure and re-backtest |
| `PAPER_TRADING` | Agent trading on paper account | Monitor performance |
| `LIVE` | Agent trading on live account | Monitor, can pause/stop |
| `PAUSED` | Agent temporarily halted | Resume or stop |
| `STOPPED` | Agent permanently deactivated | Delete or reconfigure |

### 5.2 Backtest-to-Live Gate Criteria

Before an agent can be approved for paper trading, the dashboard displays these metrics with pass/fail indicators:

| Metric | Minimum Threshold | Description |
|---|---|---|
| Total Signals | >= 50 | Must have evaluated enough signals for statistical significance |
| Win Rate | >= 45% | Percentage of profitable trades |
| Profit Factor | >= 1.2 | Gross profit / gross loss |
| Sharpe Ratio | >= 0.5 | Risk-adjusted returns |
| Max Drawdown | <= 30% | Largest peak-to-trough |
| Average Hold Time | context-dependent | Reasonable for strategy type |

These are recommendations, not hard blocks. The user can override and approve agents that don't meet all thresholds, with a warning dialog.

---

## 6. Trading Agent Architecture

### 6.1 Signal Flow

```
Data Source (Discord / Reddit / Unusual Whales / etc.)
         │
         ▼
┌──────────────────────┐
│  Connector Service   │  (ingests raw messages)
│  (Python worker)     │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Message Queue       │  (Kafka / Redis Streams)
│  topic: raw-signals  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Trading Agent       │  (OpenClaw Instance D)
│  in OpenClaw         │
│                      │
│  1. Parse message    │
│  2. Extract signal   │
│  3. Evaluate with    │
│     skills:          │
│     - Sentiment      │
│     - Technical      │
│     - Options chain  │
│     - Risk calc      │
│  4. Decision:        │
│     TAKE / PASS      │
│                      │
│  If TAKE:            │
│  5. Format trade     │
│     intent           │
│  6. POST to          │
│     execution queue  │
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Execution Queue     │  (Redis + BullMQ)
│  topic: trade-intents│
└──────────┬───────────┘
           │
           ▼
┌──────────────────────┐
│  Execution Service   │
│  1. Validate intent  │
│  2. Risk checks      │
│  3. Place order      │
│  4. Confirm fill     │
│  5. Notify monitor   │
└──────────────────────┘
```

### 6.2 Agent Evaluation Process

When a trading agent receives a signal (e.g., a Discord message saying "AAPL 180C 03/15 looking strong, entry around $3.20"):

1. **Parse**: Extract ticker (AAPL), instrument type (call option), strike (180), expiration (03/15), suggested entry ($3.20)
2. **Sentiment Check** (skill: `sentiment_analyzer`): Analyze the message tone, author track record if available
3. **Technical Check** (skill: `technical_analyst`): Pull current AAPL price, check RSI, MACD, support/resistance levels
4. **Options Chain Check** (skill: `options_chain_analyzer`): Verify the contract exists, check bid-ask spread, open interest, implied volatility, Greeks
5. **Unusual Activity Check** (skill: `unusual_whales_flow`): Check if there's unusual options activity confirming the thesis
6. **Risk Calculation** (skill: `risk_calculator`): Calculate position size based on account balance, existing exposure, max risk per trade
7. **Decision**: The agent's LLM synthesizes all skill outputs and makes a TAKE/PASS decision with written reasoning
8. **If TAKE**: Format a trade intent and push to the execution queue

### 6.3 Paired Monitoring Agent

Every trading agent is paired with a monitoring agent. When a trade is filled, the monitoring agent is notified and begins tracking the position.

**Monitoring Agent Responsibilities**:

| Responsibility | Implementation |
|---|---|
| Stop-loss enforcement | Default 20% from entry. Virtual stop (agent checks price and sends close order). Hard stop on broker side as backup. |
| Take-profit monitoring | Configurable target. Agent evaluates whether to take profit or let it run based on momentum. |
| Trailing stop | Once position is +15% or more, move stop to breakeven. At +25%, trail at 10% below high. |
| EOD close | For intraday strategies: close all positions by 3:50 PM ET. |
| Signal-based exit | If the original data source publishes a close/exit signal, the monitoring agent processes it. |
| Analyst close | If the Discord/Reddit analyst says "closing AAPL calls," the monitor triggers a close. |
| Time-based review | Every 30 minutes, the monitor re-evaluates the thesis. If conditions changed materially, recommend close. |

**Monitoring Agent Decision Matrix for Exits**:

```
IF position PnL <= -20%:
    → CLOSE (hard stop-loss, non-negotiable)

IF position PnL >= +30%:
    → Evaluate: trail stop or take profit
    → Use momentum skill to decide
    → If momentum fading: CLOSE
    → If momentum strong: TRAIL at -10% from high

IF time_held > max_hold_time:
    → CLOSE (avoid overnight risk for intraday)

IF analyst_exit_signal received:
    → CLOSE (trust the source)

IF thesis_invalidated (news, technical breakdown):
    → CLOSE (cut losses regardless of current PnL)

OTHERWISE:
    → HOLD (no action needed)
```

### 6.4 Speed Requirements

Trading agents must evaluate signals fast enough to capture the trade before the price moves significantly.

| Step | Target Latency |
|---|---|
| Message ingestion (connector → queue) | < 500ms |
| Agent evaluation (all skills) | < 10 seconds |
| Execution queue processing | < 500ms |
| Order placement (broker API) | < 2 seconds |
| **Total signal-to-order** | **< 15 seconds** |

To meet these targets:
- Use cached market data (refresh every 30-60 seconds)
- Pre-load skill contexts into agent memory
- Use fast LLM models for evaluation (Claude Haiku / GPT-4o-mini for speed, Claude Sonnet / GPT-4o for complex decisions)
- Execution service maintains persistent broker connections

### 6.5 Agent Code Generation & Predictive Models

Trading and strategy agents are not limited to prompt-based reasoning. Using OpenClaw's `python` and `shell` tools, agents can:

**Write and Execute Code**:
- Generate Python scripts for custom technical analysis calculations
- Build data pipelines to fetch, transform, and analyze market data
- Create one-off analysis scripts (e.g., "calculate the correlation between AAPL and SPY over the last 30 days")

**Build Predictive Models**:
- Train small ML models (linear regression, gradient boosting, simple neural networks) for price direction prediction
- Use scikit-learn, XGBoost, or PyTorch within sandbox environments
- Models are versioned and stored in the Artifact Store (MinIO)
- Other agents can load and use trained models via the `load_model` skill

**Example Flow**:
```
Agent receives task: "Build a model to predict SPY direction based on VIX and put/call ratio"
    │
    ├─ Agent writes Python script using skill: python_executor
    │   - Fetches historical data (VIX, PCR, SPY returns)
    │   - Trains a gradient boosting classifier
    │   - Evaluates accuracy on test set
    │   - Saves model to artifact store
    │
    ├─ Agent reports: "Model trained. Test accuracy: 62%. AUC: 0.67."
    │
    └─ Model available to other agents via: load_model("spy_direction_v1")
```

All code execution happens in sandboxed environments (Docker containers with no host access) to prevent any damage to the system.

---

## 7. Strategy Agent Architecture

### 7.1 How Strategy Agents Differ from Trading Agents

| Aspect | Trading Agent | Strategy Agent |
|---|---|---|
| Trigger | External signal (Discord, Reddit, etc.) | Internal heartbeat/cron |
| Data source | Messages from connectors | Market data APIs directly |
| Decision model | LLM evaluates human-generated signals | Algorithmic rules (with optional LLM oversight) |
| Frequency | Event-driven (whenever a signal arrives) | Time-driven (every N minutes) |
| Independence | Depends on external data quality | Self-contained |

### 7.2 Runtime Model

Strategy agents run in their assigned OpenClaw instance with a HEARTBEAT.md file that defines their schedule:

```markdown
## Strategy: RSI Reversal — SPY, QQQ

### Schedule
- Active: weekdays 9:30 AM - 3:50 PM ET
- Frequency: every 5 minutes

### On Each Tick
1. Fetch 5-minute bars for SPY, QQQ (last 100 bars)
2. Calculate RSI(14) for each
3. Check for entry signals:
   - RSI crosses below 30 from above → BUY signal
   - RSI crosses above 70 from below → SELL signal (if holding)
4. If signal:
   - Calculate position size (max 5% of account per trade)
   - POST trade intent to execution queue
   - Log: ticker, RSI value, signal type, size
5. If no signal:
   - Log: "No signal. SPY RSI=52.3, QQQ RSI=48.7"

### EOD Rule
- At 3:50 PM: close all open positions for this strategy
- Log daily summary: trades taken, PnL, final RSI values

### Data Output
- Write all logs to /workspace/strategy_logs/<date>.jsonl
- Write current state to /workspace/strategy_state.json
```

### 7.3 Strategy Data Pipeline

Strategy agents write their state and logs to files/database that the dashboard reads:

```
Strategy Agent (OpenClaw)
    │
    ├──► /workspace/strategy_state.json
    │    {
    │      "strategy": "RSI Reversal",
    │      "instruments": ["SPY", "QQQ"],
    │      "positions": [{"ticker": "SPY", "side": "long", "entry": 450.2}],
    │      "last_check": "2026-03-03T14:30:00Z",
    │      "signals_today": 3,
    │      "pnl_today": 127.50
    │    }
    │
    ├──► /workspace/strategy_logs/2026-03-03.jsonl
    │    (append-only log of every tick and decision)
    │
    └──► POST /api/v2/strategy-heartbeat
         (periodic push to dashboard API for real-time display)
```

The dashboard polls the strategy heartbeat API or receives WebSocket pushes to update the Strategy Agents tab.

---

## 8. Position Monitoring

### 8.1 Architecture

Position monitoring is a two-layer system:

**Layer 1 — Per-Agent Monitoring Agent** (OpenClaw):
- Each trading/strategy agent has a paired monitoring agent
- Runs in the same OpenClaw instance
- Has full context of the trading agent's thesis and reasoning
- Makes intelligent exit decisions (trailing stops, thesis invalidation)

**Layer 2 — Global Position Monitor** (Backend Service):
- Aggregates all positions across all agents and accounts
- Enforces hard limits (daily loss, max exposure, circuit breakers)
- Cannot be overridden by any agent
- Kills all trading if total portfolio loss exceeds threshold

### 8.2 Stop-Loss Strategy

| Level | Trigger | Action | Overridable |
|---|---|---|---|
| Hard stop-loss | Position PnL <= -20% | Immediate market close | No |
| Soft stop-loss | Position PnL <= -10% | Agent re-evaluates, may close | Yes (agent decides) |
| Trailing stop | Position PnL was >= +15%, now dropped 10% from high | Close to lock in profits | No |
| Time stop | Position held > max hold time | Close regardless of PnL | No |
| Daily loss limit | Account daily loss >= -5% | Pause all agents on account | No |
| Portfolio circuit breaker | Total portfolio loss >= -10% in one day | Kill switch: close ALL positions, pause ALL agents | No |

### 8.3 Exit Decision Flow

```
Every 30 seconds (monitoring agent loop):
    │
    ├─ Fetch current price for all monitored positions
    │
    ├─ For each position:
    │   ├─ Calculate unrealized PnL
    │   ├─ Check hard stop-loss (-20%) → CLOSE if hit
    │   ├─ Check trailing stop → CLOSE if triggered
    │   ├─ Check time stop → CLOSE if exceeded
    │   ├─ Check for exit signals from data source
    │   │   └─ If analyst said "close" → CLOSE
    │   ├─ Every 30 minutes: full thesis re-evaluation
    │   │   ├─ Re-run technical analysis
    │   │   ├─ Check for adverse news
    │   │   └─ If thesis broken → CLOSE
    │   └─ If none of above: HOLD
    │
    └─ Report status to dashboard via heartbeat
```

### 8.4 Profit-Taking Strategy

When a position is profitable, the monitoring agent uses a graduated approach:

| PnL Range | Behavior |
|---|---|
| 0% to +15% | Hold. Let the trade develop. |
| +15% to +25% | Move stop to breakeven. Agent begins watching for momentum fade. |
| +25% to +50% | Trail stop at 10% below the high water mark. |
| +50% to +100% | Take partial profits (close 50% of position). Trail remainder at 15% below high. |
| > +100% | Take 75% profits. Trail final 25% at 20% below high. |

The monitoring agent can also close based on momentum analysis — if RSI shows divergence, volume is declining, or the broader market is reversing, it may recommend closing even within "hold" ranges.

---

## 9. Dev Agent & Reinforcement Learning

### 9.1 Dev Agent Overview

The Dev Agent is a specialized OpenClaw agent with elevated permissions that continuously monitors all other agents in the system. It operates as the "AI managing AI" — detecting failures, diagnosing root causes, auto-fixing code, tuning parameters, and learning from outcomes via reinforcement learning.

The Dev Agent runs in OpenClaw Instance C (Promotion & Risk) with access to all agent workspaces, logs, and performance data. It has its own dedicated workspace and memory.

### 9.2 Monitoring Duties

The Dev Agent continuously gathers data on every strategy and trading agent:

| Monitored Metric | Trigger Condition |
|---|---|
| Win rate | Drops below historical average by > 15% |
| Consecutive losses | 5+ losing trades in a row |
| Drawdown | Exceeds 10% in a single day |
| Trade frequency | Abnormally high or zero trades (stall detection) |
| Error rate | Any runtime exceptions or API failures |
| Strategy drift | Live performance deviates from backtest by > 2 standard deviations |
| Latency | Signal-to-order time exceeds 30 seconds |
| Agent health | Agent process not responding to heartbeat |

### 9.3 Issue Detection and Diagnosis

When an anomaly is detected, the Dev Agent follows a structured diagnosis flow:

```
Anomaly Detected
      │
      ▼
┌──────────────────────────────────┐
│  1. GATHER CONTEXT               │
│  - Last N trades of the agent    │
│  - Agent's strategy parameters   │
│  - Error logs / stack traces     │
│  - Market regime at time of      │
│    failure                       │
│  - Connector health status       │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  2. CLASSIFY ISSUE               │
│  - Software bug (exception)      │
│  - Strategy underperformance     │
│  - External failure (data feed)  │
│  - Market regime mismatch        │
│  - Configuration error           │
└──────────────┬───────────────────┘
               │
               ▼
┌──────────────────────────────────┐
│  3. DETERMINE ACTION             │
│  - Fix code (Self-Debugging)     │
│  - Tune parameters (Optimizer)   │
│  - Pause agent                   │
│  - Reduce position sizes         │
│  - Restart connector             │
│  - Switch to backup data source  │
│  - Recommend human review        │
└──────────────────────────────────┘
```

### 9.4 Reinforcement Learning Feedback Loop

The Dev Agent treats each intervention as an action in an RL environment:

**State Space**: Vector representation of the troubled agent's recent performance — win rate, PnL trajectory, trade frequency, error count, market regime classification, time of day.

**Action Space**: The set of possible interventions — tweak parameter (which parameter, by how much), pause agent, reduce size, fix code, switch data source, do nothing.

**Reward Function**: Measured change in the target agent's performance in the period following the intervention:
- Positive reward: agent PnL improves, win rate recovers, errors stop
- Negative reward: agent PnL worsens, new errors introduced, unnecessary pause cost opportunity

**Algorithm**: Q-learning or policy gradient (PPO) trained on accumulated intervention history. State-action-reward tuples are stored and used for batch updates.

**Learning Loop**:
```
OBSERVE agent performance metrics (state)
    │
    ▼
SELECT intervention action (policy)
    │
    ▼
EXECUTE intervention (fix, tune, pause)
    │
    ▼
WAIT observation period (1 hour to 1 day)
    │
    ▼
MEASURE outcome (reward)
    │
    ▼
UPDATE policy (Q-values or policy weights)
    │
    ▼
REPEAT
```

Over time, the Dev Agent learns patterns like:
- "Mean reversion agents lose in strong trends — pause them when ADX > 40"
- "Widening stop-loss by 0.5% fixes short-squeeze losses better than pausing"
- "Data feed errors resolve in < 5 minutes — wait before escalating"

### 9.5 Auto-Repair and Code Generation

When the Dev Agent detects a software bug:

1. **Retrieve** the error traceback and recent agent code
2. **Analyze** using LLM (Self-Debugging skill) — identify the bug
3. **Generate** a code fix (patch to the skill or script)
4. **Test** the fix in sandbox (run against recent data)
5. **Apply** the hot-patch to the agent's skill file in OpenClaw
6. **Verify** the agent resumes normal operation

For performance issues, the Dev Agent can:
- Use the Parameter Tuning skill to grid-search better values on recent data
- Run a quick backtest to validate before applying
- Generate entirely new strategy variations by modifying existing code

### 9.6 Dev Dashboard (Admin-Only)

A dedicated admin-only page showing the Dev Agent's activity:

**Incident Feed**:
- Chronological list of all detected issues
- Each entry: timestamp, agent affected, issue type, severity, action taken, outcome
- Status: `detected` → `diagnosing` → `fixing` → `monitoring` → `resolved` / `escalated`

**RL Metrics Panel**:
- Cumulative reward over time (chart)
- Action distribution (pie chart — how often each intervention type is chosen)
- Success rate per action type
- Policy confidence scores

**Code Changes Log**:
- Every code fix the Dev Agent has applied
- Diff view: before/after for each patch
- Rollback button per change

**Agent Health Matrix**:
- Grid of all agents with color-coded health scores
- Click to see the Dev Agent's assessment of each agent
- Recommendations queue: fixes waiting for admin approval (for high-impact changes)

**Performance Comparison**:
- Before/after metrics for each Dev Agent intervention
- Shows whether the system is actually improving over time

---

## 10. Agent-to-Agent Communication

### 10.1 Why Agents Need to Talk

A trading agent receiving a headline about AAPL earnings can make a better decision if it can:
1. Ask the Options Flow agent: "Is there unusual call activity on AAPL right now?"
2. Ask the Technical Analysis agent: "What are AAPL's key support/resistance levels?"
3. Ask another Trading agent: "Are you also seeing bullish signals on AAPL from your sources?"

This consensus-building increases the probability of successful trades and reduces false signals.

### 10.2 Communication Architecture

**Same-Instance Communication** (agents on the same OpenClaw instance):
- OpenClaw's built-in `agentToAgent` messaging via shared sessions
- Direct memory sharing through workspace files
- Low latency (< 100ms)

**Cross-Instance Communication** (agents on different VPS nodes):
- Event Bus (Redis Streams / NATS) pub/sub topics
- Each agent type has a dedicated topic: `agent.trading.*`, `agent.strategy.*`, `agent.analysis.*`
- Broadcast channel `agent.broadcast` for system-wide alerts
- Latency depends on network (typically < 500ms over WireGuard VPN)

### 10.3 Communication Protocol

All inter-agent messages follow a structured JSON format:

```json
{
  "message_id": "msg_abc123",
  "from_agent": "echo_trading_agent",
  "from_instance": "oc-live-trading-01",
  "to_agent": "options_flow_analyst",
  "to_instance": "oc-data-research-01",
  "intent": "confirm_signal",
  "data": {
    "ticker": "AAPL",
    "direction": "bullish",
    "source": "Discord #earnings-plays",
    "context": "Analyst says AAPL 190C 03/15 looking strong ahead of earnings"
  },
  "response_expected": true,
  "timeout_ms": 5000,
  "timestamp": "2026-03-03T14:30:00Z"
}
```

**Response Format**:
```json
{
  "message_id": "msg_abc124",
  "in_reply_to": "msg_abc123",
  "from_agent": "options_flow_analyst",
  "intent": "signal_confirmation",
  "data": {
    "confirmed": true,
    "confidence": 0.78,
    "supporting_evidence": "Large AAPL call sweeps detected: 5000x 190C 03/15 at $3.40 ask",
    "additional_context": "IV rank 62%, open interest building at 190 strike"
  },
  "timestamp": "2026-03-03T14:30:03Z"
}
```

### 10.4 Communication Patterns

| Pattern | Description | Example |
|---|---|---|
| **Request-Response** | Agent asks a question, expects a reply | Trading agent asks Options Flow agent for confirmation |
| **Broadcast** | Agent announces to all | Dev Agent broadcasts "Circuit breaker triggered, all agents pause" |
| **Pub-Sub** | Agents subscribe to topics of interest | All trading agents subscribe to `agent.analysis.sentiment` for real-time sentiment updates |
| **Chain** | Sequential consultation across agents | Signal → Sentiment Agent → Technical Agent → Risk Agent → Decision |
| **Consensus** | Multiple agents vote on a trade | 3 agents confirm bullish AAPL → proceed; 1 confirm, 2 reject → pass |

### 10.5 Consensus-Based Trading

For high-conviction trades, agents can use a consensus protocol:

```
Trading Agent receives signal: "AAPL bullish"
    │
    ├─ Sends confirm_signal to Options Flow Agent
    │   Response: confirmed (confidence 0.78)
    │
    ├─ Sends confirm_signal to Technical Analysis Agent
    │   Response: confirmed (confidence 0.65, "above 20 EMA, RSI 55")
    │
    ├─ Sends confirm_signal to Sentiment Agent
    │   Response: neutral (confidence 0.50, "mixed Reddit sentiment")
    │
    ├─ Aggregates: 2/3 confirmed, average confidence 0.64
    │
    └─ Decision: TAKE (threshold met: >= 2/3 confirmations, avg confidence > 0.6)
```

The required confirmation count and confidence threshold are configurable per agent.

---

## 11. Task Board & Automations

### 11.1 Task Board Overview

The Task Board is a new dashboard tab that operates as a kanban-style board where users create agents with specific roles and assign them tasks. This is different from Trading Agents (which react to data source signals) and Strategy Agents (which follow algorithmic rules). Task Board agents are role-based workers — a virtual trading firm.

**Reused Components**: Built on the existing `SprintBoard` and `TaskDetail` pages from Phoenix v1, using `@dnd-kit/core` and `@dnd-kit/sortable` for drag-and-drop.

### 11.2 Agent Roles

Users create agents from a role template:

| Role | Description | Example Tasks |
|---|---|---|
| **Day Trader** | Executes intraday trades based on assigned tasks | "Trade AAPL momentum today", "Scalp SPY 0DTE calls" |
| **Technical Analyst** | Analyzes charts and produces reports | "Analyze NVDA daily chart", "Find breakout candidates in NASDAQ 100" |
| **Risk Analyzer** | Evaluates portfolio risk and suggests adjustments | "Review portfolio correlation", "Stress test for 5% market drop" |
| **Market Research Analyst** | Researches macro and sector trends | "Summarize Fed meeting implications", "Analyze semiconductor sector outlook" |
| **Options Specialist** | Analyzes options chains and strategies | "Find best iron condor on SPY for this week", "Analyze AAPL earnings straddle" |
| **News Analyst** | Monitors and interprets breaking news | "Watch for FDA announcements today", "Summarize pre-market movers" |
| **Quant Developer** | Builds models and runs data analysis | "Build a momentum factor model", "Backtest pairs trading on MSFT/GOOGL" |
| **Custom** | User-defined role with custom system prompt | Any task the user specifies |

### 11.3 Task Board UI

**Kanban Columns**: Backlog → In Progress → Under Review → Completed

**Task Card Fields**:
- Task title and description (natural language)
- Assigned agent (role + instance)
- Priority (critical, high, medium, low)
- Due date / deadline
- Status
- Output / deliverable (text, file, chart, trade recommendation)
- Labels / tags

**Agent-Created Tasks**: Agents can also create tasks on the board. For example:
- A Market Research Analyst might create a task: "AAPL earnings tomorrow — need options strategy analysis"
- A Risk Analyzer might create: "Portfolio heat approaching 25% — need rebalancing review"

These agent-created tasks appear with an "Agent" badge and can be assigned to other agents or flagged for human review.

### 11.4 Automations Panel

A separate section within the Task Board tab for configuring recurring automations:

**Natural Language Task Input**:
- Text input: "Give me a morning briefing of the stock market every weekday at 8:00 AM"
- System parses into: cron schedule + agent role + task description + delivery channel
- User confirms and edits the parsed configuration

**Automation Configuration**:

| Field | Description |
|---|---|
| Name | "Morning Market Briefing" |
| Schedule | Cron expression or natural language ("every weekday at 8:00 AM ET") |
| Agent Role | Market Research Analyst |
| Instance | Auto-select or specific instance |
| Task Description | "Compile pre-market summary: futures, key earnings, economic events, sector movers" |
| Delivery Channel | Telegram / Discord / WhatsApp / Dashboard notification |
| Active | Toggle on/off |

**Example Automations**:

| Automation | Schedule | Agent Role | Delivery |
|---|---|---|---|
| Morning Market Briefing | Weekdays 8:00 AM | Market Research Analyst | Telegram |
| End-of-Day Summary | Weekdays 4:15 PM | Risk Analyzer | Discord |
| Apple Earnings Analysis | One-shot: March 5 at 7:00 AM | Options Specialist | Dashboard + Telegram |
| Weekly Portfolio Review | Sundays 6:00 PM | Risk Analyzer | Email |
| Options Flow Alert | Every 30 min during market hours | Options Specialist | WhatsApp |
| Sector Rotation Check | Weekly Mondays 9:00 AM | Market Research Analyst | Discord |

**How It Works**:
1. User configures automation in dashboard UI
2. Backend creates a cron job entry in the database
3. At scheduled time, Orchestrator enqueues a job
4. Job is dispatched to an available OpenClaw instance
5. A temporary or permanent agent is spun up with the specified role
6. Agent executes the task, produces output
7. Output is delivered via the configured channel AND stored on the dashboard
8. For one-shot tasks, the agent workspace is cleaned up after delivery

### 11.5 Bidirectional Communication Channels

Users interact with agents through configured messaging platforms:

**Supported Channels**:

| Channel | Send Alerts | Receive Commands | Implementation |
|---|---|---|---|
| Discord | Yes | Yes | OpenClaw native Discord bot account |
| Telegram | Yes | Yes | OpenClaw native Telegram bot account |
| WhatsApp | Yes | Limited (via Meta Cloud API, existing `shared/whatsapp/sender.py`) | Meta Business API |
| Dashboard | Yes | Yes | WebSocket + REST API |

**Outbound** (Agent → User):
- Trade alerts: "Agent Echo bought 100 AAPL @ $185.50"
- Task completions: "Morning briefing ready — [view on dashboard]"
- Warnings: "Portfolio drawdown at 8%, approaching 10% circuit breaker"
- Dev Agent reports: "Fixed Agent Omega's stop-loss calculation bug"

**Inbound** (User → Agent):
- Commands: "Pause agent Echo"
- Tasks: "Analyze TSLA chart for tomorrow"
- Questions: "What is my current portfolio exposure?"
- Overrides: "Close all AAPL positions now"

**Implementation**: OpenClaw natively supports Discord and Telegram as channel types via bot accounts. Each agent can be bound to specific channels in `openclaw.json` bindings. The dashboard backend routes inbound messages to the appropriate agent via the Event Bus.

---

## 12. Skill Catalog & Skill Development Framework

Skills are the building blocks of agent intelligence. Each skill is a `SKILL.md` file that teaches an OpenClaw agent how to perform a specific task.

### 12.1 Data Retrieval Skills (18 skills)

| # | Skill Name | Description |
|---|---|---|
| 1 | `fetch-stock-quotes` | Get real-time stock quotes from broker/market data API |
| 2 | `fetch-options-chain` | Retrieve full options chain for a ticker (strikes, expirations, Greeks) |
| 3 | `fetch-historical-bars` | Get OHLCV bars for any timeframe (1m to monthly) |
| 4 | `fetch-unusual-whales-flow` | Pull options flow data from Unusual Whales API |
| 5 | `fetch-dark-pool-data` | Get dark pool print data from Unusual Whales |
| 6 | `fetch-news-headlines` | Aggregate news from Finnhub, NewsAPI, Benzinga |
| 7 | `fetch-earnings-calendar` | Get upcoming earnings dates and estimates |
| 8 | `fetch-economic-calendar` | Get economic events (FOMC, CPI, NFP, etc.) |
| 9 | `fetch-insider-trades` | Congressional and corporate insider transaction data |
| 10 | `fetch-social-sentiment` | Aggregate sentiment from Reddit, Twitter, StockTwits |
| 11 | `fetch-sector-performance` | Sector ETF performance and rotation data |
| 12 | `fetch-market-breadth` | Advance/decline, new highs/lows, McClellan oscillator |
| 13 | `fetch-vix-data` | VIX spot, futures, term structure |
| 14 | `fetch-gex-data` | Gamma exposure levels by strike (Unusual Whales / custom) |
| 15 | `fetch-premarket-data` | Pre-market movers, gap analysis, futures |
| 16 | `fetch-order-book` | Level II order book data — bids, asks, depth, imbalances |
| 17 | `fetch-level2-flow` | Time and sales tape data for detecting large block trades |
| 18 | `fetch-economic-indicators` | Fear & Greed index, yield curve, Fed funds rate, CPI |

### 12.2 Analysis Skills (25 skills)

| # | Skill Name | Description |
|---|---|---|
| 16 | `technical-analysis-basic` | Calculate RSI, MACD, Bollinger Bands, moving averages |
| 17 | `technical-analysis-advanced` | Ichimoku, Fibonacci, Elliott Wave, harmonic patterns |
| 18 | `support-resistance-levels` | Identify key support/resistance from price history |
| 19 | `volume-analysis` | Volume profile, OBV, relative volume, VWAP analysis |
| 20 | `options-greeks-analyzer` | Analyze delta, gamma, theta, vega for position sizing |
| 21 | `implied-volatility-analyzer` | IV rank, IV percentile, skew analysis, term structure |
| 22 | `sentiment-classifier` | Classify text as bullish/bearish/neutral (FinBERT or LLM) |
| 23 | `trade-signal-parser` | Parse unstructured messages into structured trade signals |
| 24 | `news-impact-analyzer` | Assess likely price impact of a news headline |
| 25 | `earnings-analyzer` | Analyze earnings results vs. expectations, estimate reaction |
| 26 | `correlation-analyzer` | Calculate correlation between instruments, detect divergences |
| 27 | `momentum-scorer` | Score momentum across multiple timeframes |
| 28 | `mean-reversion-detector` | Detect overextended conditions ripe for reversion |
| 29 | `trend-strength-analyzer` | ADX, moving average alignment, trend duration |
| 30 | `pattern-recognition` | Chart patterns: head & shoulders, double top/bottom, flags, wedges |
| 31 | `options-flow-interpreter` | Interpret unusual options activity and infer institutional positioning |
| 32 | `sector-rotation-analyzer` | Identify which sectors are leading/lagging, rotation signals |
| 33 | `macro-regime-classifier` | Classify current market regime: risk-on, risk-off, ranging, trending |
| 34 | `put-call-ratio-analyzer` | Analyze put/call ratios for contrarian signals |
| 35 | `whale-tracker` | Track large institutional trades and dark pool activity |
| 36 | `chart-pattern-recognition` | Detect chart patterns: flags, double tops, head-and-shoulders, wedges |
| 37 | `order-book-imbalance` | Analyze Level II order book for supply/demand imbalances |
| 38 | `volume-flow-scanner` | Scan for unusual volume spikes and block trades across a watchlist |
| 39 | `options-max-pain-calculator` | Calculate max pain strike and pin risk for options expiration |
| 40 | `relative-strength-ranker` | Rank stocks by relative strength vs. sector/index for momentum |

### 12.3 Strategy Skills (15 skills)

| # | Skill Name | Description |
|---|---|---|
| 36 | `strategy-rsi-reversal` | RSI oversold/overbought reversal strategy logic |
| 37 | `strategy-macd-crossover` | MACD signal line crossover strategy |
| 38 | `strategy-breakout` | Price breakout above resistance with volume confirmation |
| 39 | `strategy-opening-range` | Opening range breakout (ORB) strategy for intraday |
| 40 | `strategy-vwap-reversion` | Mean reversion to VWAP strategy |
| 41 | `strategy-iron-condor` | Weekly iron condor on indices with IV rank filter |
| 42 | `strategy-wheel` | Wheel strategy (sell puts, get assigned, sell calls) |
| 43 | `strategy-covered-call` | Covered call writing on held positions |
| 44 | `strategy-momentum` | Multi-factor momentum (price + volume + relative strength) |
| 45 | `strategy-pairs-trading` | Statistical arbitrage between correlated instruments |
| 46 | `strategy-gap-fill` | Trade gap fills on stocks gapping up/down at open |
| 47 | `strategy-earnings-drift` | Post-earnings announcement drift strategy |
| 48 | `strategy-0dte-scalp` | 0DTE options scalping based on SPX levels and GEX |
| 49 | `strategy-dividend-capture` | Buy before ex-date, sell after with covered calls |
| 50 | `strategy-sector-rotation` | Rotate into strongest sectors monthly |

### 12.4 Execution Skills (12 skills)

| # | Skill Name | Description |
|---|---|---|
| 51 | `place-stock-order` | Place market/limit stock orders via broker API |
| 52 | `place-option-order` | Place single-leg option orders |
| 53 | `place-spread-order` | Place multi-leg option spreads (verticals, iron condors) |
| 54 | `calculate-position-size` | Risk-based position sizing (% of account, Kelly criterion) |
| 55 | `format-trade-intent` | Convert agent decision into standardized trade intent JSON |
| 56 | `cancel-order` | Cancel open/pending orders |
| 57 | `modify-order` | Modify existing order (price, quantity) |
| 58 | `close-position` | Close an entire position (market or limit) |
| 59 | `close-partial-position` | Close a percentage of a position |
| 60 | `close-all-positions` | Emergency: close everything on an account |
| 61 | `smart-order-router` | Route orders optimally across brokers for best execution |
| 62 | `multi-asset-hedger` | Calculate and execute hedges (e.g., buy QQQ puts against long tech) |

### 12.5 Risk & Monitoring Skills (10 skills)

| # | Skill Name | Description |
|---|---|---|
| 61 | `risk-calculator` | Calculate VaR, max loss, portfolio heat |
| 62 | `position-monitor` | Track unrealized PnL, check stop-loss levels |
| 63 | `trailing-stop-manager` | Implement and manage trailing stop logic |
| 64 | `daily-pnl-tracker` | Track daily PnL across all positions |
| 65 | `drawdown-monitor` | Monitor and alert on drawdown thresholds |
| 66 | `exposure-calculator` | Calculate portfolio exposure by sector, ticker, strategy |
| 67 | `circuit-breaker` | Trigger kill switch when loss limits are breached |
| 68 | `correlation-risk-checker` | Check if new trade adds correlated risk to portfolio |
| 69 | `eod-position-closer` | End-of-day position closing for intraday strategies |
| 70 | `overnight-risk-assessor` | Evaluate overnight holding risk based on events calendar |

### 12.6 Utility Skills (15 skills)

| # | Skill Name | Description |
|---|---|---|
| 71 | `backtest-runner` | Execute a strategy backtest against historical data |
| 72 | `backtest-reporter` | Generate performance report from backtest results |
| 73 | `strategy-optimizer` | Run parameter optimization (grid search or genetic) |
| 74 | `log-trade-decision` | Write structured decision log for audit trail |
| 75 | `notify-dashboard` | Push status/event to dashboard API |
| 76 | `notify-discord` | Send notification to Discord channel |
| 77 | `notify-email` | Send email notification (alerts, daily summary) |
| 78 | `data-cache-manager` | Cache and retrieve market data (Parquet/TimescaleDB) |
| 79 | `performance-calculator` | Calculate Sharpe, Sortino, max drawdown, profit factor |
| 80 | `equity-curve-generator` | Generate equity curve data from trade history |
| 81 | `trade-journal-writer` | Write detailed trade journal entry with reasoning |
| 82 | `market-hours-checker` | Check if market is open, pre-market, after-hours, or closed |
| 83 | `options-expiration-tracker` | Track upcoming expirations for held options |
| 84 | `dividend-date-checker` | Check ex-dividend dates for held positions |
| 85 | `broker-account-status` | Get account balance, buying power, margin status |

### 12.7 Advanced/AI Skills (20 skills)

| # | Skill Name | Description |
|---|---|---|
| 86 | `llm-trade-evaluator` | Use LLM to synthesize all data and evaluate a trade idea |
| 87 | `llm-thesis-validator` | Re-evaluate an existing trade thesis with current data |
| 88 | `llm-strategy-generator` | Generate new strategy ideas from market conditions |
| 89 | `llm-risk-narrator` | Generate human-readable risk assessment |
| 90 | `llm-market-summary` | Generate morning market briefing |
| 91 | `llm-trade-debrief` | Post-trade analysis: what went right/wrong |
| 92 | `agent-debate-bull-bear` | Bull vs. bear debate between two agent contexts |
| 93 | `agent-consensus-builder` | Aggregate signals from multiple agents into consensus |
| 94 | `anomaly-detector` | Detect unusual patterns in price, volume, or flow data |
| 95 | `regime-change-detector` | Detect shifts in market regime (volatile, trending, ranging) |
| 96 | `news-event-classifier` | Classify news events by expected market impact (high/med/low) |
| 97 | `discord-message-quality-scorer` | Score Discord trade alerts by historical accuracy |
| 98 | `strategy-drift-detector` | Detect when live performance diverges from backtest |
| 99 | `adaptive-stop-loss` | ML-based dynamic stop-loss that adapts to volatility |
| 100 | `multi-timeframe-confluence` | Identify setups where multiple timeframes align |
| 101 | `python-code-executor` | Write and execute arbitrary Python code in sandbox for custom analysis |
| 102 | `ml-model-trainer` | Train ML models (sklearn, XGBoost, PyTorch) on market data |
| 103 | `ml-model-loader` | Load a pre-trained model from artifact store and run inference |
| 104 | `self-debugger` | Analyze error tracebacks and generate code fixes |
| 105 | `parameter-optimizer` | Grid search or genetic optimization of strategy parameters |
| 106 | `memory-compactor` | Summarize and compress agent session history to free context |
| 107 | `knowledge-base-query` | Query a vector database of historical trading events and outcomes |
| 108 | `skill-loader` | Dynamically load a new skill from ClawHub or central repo at runtime |
| 109 | `portfolio-rebalancer` | Calculate and execute portfolio rebalancing across agents |
| 110 | `agent-to-agent-messenger` | Send structured messages to other agents and handle responses |
| 111 | `telegram-notifier` | Send messages and receive commands via Telegram bot |
| 112 | `discord-notifier` | Send messages and receive commands via Discord bot |
| 113 | `whatsapp-notifier` | Send alerts via WhatsApp using Meta Cloud API |
| 114 | `task-board-updater` | Create, update, and complete tasks on the dashboard Task Board |
| 115 | `cron-scheduler` | Create and manage scheduled automation jobs |

### 12.8 Skill Development Framework

A standardized framework for creating, testing, and deploying new skills.

**Skill Template**:

```markdown
---
name: my-custom-skill
version: 1.0.0
description: Short description of what this skill does
category: analysis | data | execution | risk | utility | advanced
tools_required:
  - python
  - shell
dependencies:
  - fetch-stock-quotes
  - technical-analysis-basic
---

# My Custom Skill

## Purpose
Detailed description of what this skill accomplishes.

## Inputs
- `ticker` (string, required): Stock symbol
- `timeframe` (string, optional, default "1d"): Data timeframe

## Workflow
1. Fetch data using `fetch_stock_quotes` for the given ticker
2. Run analysis (describe step by step)
3. Return structured result

## Output Format
```json
{
  "result": "...",
  "confidence": 0.0,
  "details": {}
}
```

## Guardrails
- Do not execute trades directly from this skill
- Do not expose API keys in output
- Timeout: 30 seconds maximum
```

**Skill Development Workflow**:

```
1. AUTHOR
   └─ Create SKILL.md from template (via dashboard UI or local editor)

2. TEST
   └─ Run skill in sandbox against test data
   └─ Validate outputs match expected format
   └─ Check for errors, timeouts, security issues

3. REVIEW
   └─ Automated checks: lint, guardrail validation, dependency check
   └─ Optional: peer review by admin

4. DEPLOY
   └─ Push to central skill repository
   └─ Sync triggers push to all OpenClaw instances
   └─ Skill becomes available to agents

5. VERSION
   └─ Semantic versioning (major.minor.patch)
   └─ Breaking changes increment major version
   └─ Rollback to previous version with one click
```

**Dashboard Skill Builder**:
- Create new skills from templates directly in the dashboard UI
- Code editor with syntax highlighting for SKILL.md
- Live preview of parsed skill metadata
- "Test in Sandbox" button to run the skill against sample data
- Version history with diff view
- One-click deploy to all instances

---

## 13. Connector Framework

### 13.1 Connector Architecture

All connectors follow a unified interface:

```python
class BaseConnector:
    connector_type: str        # "discord", "reddit", "unusual_whales", etc.
    config: ConnectorConfig    # Credentials, filters, settings
    status: str                # "connected", "disconnected", "error"

    async def connect() -> bool
    async def disconnect() -> None
    async def test_connection() -> ConnectionTestResult
    async def start_ingestion() -> None  # Begin consuming messages
    async def stop_ingestion() -> None
    async def get_historical(start: datetime, end: datetime) -> list[RawMessage]
```

Every connector publishes normalized messages to the event bus:

```json
{
  "id": "msg_abc123",
  "connector_type": "discord",
  "connector_id": "disc_001",
  "source": {
    "server": "Trading Alerts Pro",
    "channel": "#options-flow",
    "author": "TraderX",
    "author_id": "discord_user_456"
  },
  "content": "AAPL 180C 03/15 looking strong, entry around $3.20",
  "timestamp": "2026-03-03T14:30:00Z",
  "metadata": {
    "message_type": "trade_alert",
    "attachments": [],
    "reactions": {"fire": 5, "rocket": 3}
  }
}
```

### 13.2 Connector Configurations

**Discord Connector**:
```json
{
  "type": "discord",
  "bot_token": "encrypted:...",
  "servers": [
    {
      "server_id": "123456",
      "name": "Trading Alerts Pro",
      "channels": [
        {
          "channel_id": "789012",
          "name": "#options-flow",
          "assigned_agents": ["agent_echo", "agent_sage"],
          "filters": {
            "authors": [],
            "keywords": ["call", "put", "entry", "target"],
            "ignore_bots": true
          }
        }
      ]
    }
  ]
}
```

**Reddit Connector**:
```json
{
  "type": "reddit",
  "client_id": "encrypted:...",
  "client_secret": "encrypted:...",
  "subreddits": [
    {
      "name": "wallstreetbets",
      "sort": "new",
      "filters": {
        "flairs": ["DD", "YOLO", "Options"],
        "min_score": 10,
        "keywords": []
      },
      "assigned_agents": ["agent_wsb_scanner"]
    }
  ],
  "poll_interval_seconds": 30
}
```

**Unusual Whales Connector**:
```json
{
  "type": "unusual_whales",
  "api_key": "encrypted:...",
  "feeds": [
    {
      "feed_type": "options_flow",
      "filters": {
        "min_premium": 50000,
        "flow_types": ["sweep", "block"],
        "tickers": [],
        "sentiment": ["bullish", "bearish"]
      },
      "delivery": "websocket",
      "assigned_agents": ["agent_flow_trader"]
    },
    {
      "feed_type": "dark_pool",
      "filters": {
        "min_notional": 2000000
      },
      "delivery": "polling",
      "poll_interval_seconds": 60,
      "assigned_agents": ["agent_dark_pool_analyst"]
    }
  ]
}
```

**Broker Connector**:
```json
{
  "type": "alpaca",
  "mode": "paper",
  "api_key": "encrypted:...",
  "api_secret": "encrypted:...",
  "base_url": "https://paper-api.alpaca.markets",
  "capabilities": ["stocks", "options", "crypto"],
  "risk_config": {
    "max_position_pct": 10,
    "daily_loss_limit_pct": 5,
    "max_concurrent_positions": 20
  }
}
```

### 13.3 Supported Connectors Summary

| Connector | Type | Auth | Delivery | Historical |
|---|---|---|---|---|
| Discord | Data Source | Bot Token (OAuth2) | Real-time (WebSocket) | Yes (message history) |
| Reddit | Data Source | OAuth2 (client credentials) | Polling (30s default) | Yes (API search) |
| Twitter/X | Data Source | Bearer Token (v2 API) | Filtered Stream | Limited |
| Unusual Whales | Data Source | API Key | WebSocket + REST | Yes (historical endpoints) |
| Finnhub | Data Source | API Key | WebSocket + REST | Yes |
| NewsAPI | Data Source | API Key | Polling | Yes (30 days) |
| Custom Webhook | Data Source | API Key / HMAC | Push (HTTP POST) | No |
| Alpaca | Broker | API Key + Secret | REST + WebSocket | N/A |
| Interactive Brokers | Broker | TWS API (socket) | Socket | N/A |
| Robinhood | Broker | Username/Password + MFA | REST | N/A |
| Tradier | Broker | Access Token | REST | N/A |
| Discord | Communication | Bot Token | Real-time (native OpenClaw) | N/A |
| Telegram | Communication | Bot Token | Real-time (native OpenClaw) | N/A |
| WhatsApp | Communication | Meta Cloud API | REST (outbound only) | N/A |

---

## 14. Backtesting Engine

### 14.1 Architecture

The backtesting engine runs in a sandboxed environment (Docker/Firejail) to prevent any interference with live systems.

```
Backtest Request (from Orchestrator)
         │
         ▼
┌──────────────────────────┐
│  Sandbox Container       │
│  (Docker, no host access)│
│                          │
│  ┌────────────────────┐  │
│  │  Data Loader       │  │
│  │  Load historical   │  │
│  │  bars, messages,   │  │
│  │  news from cache   │  │
│  └────────┬───────────┘  │
│           │              │
│  ┌────────▼───────────┐  │
│  │  Simulation Engine │  │
│  │  - Replay messages │  │
│  │  - Feed to agent   │  │
│  │  - Record decisions│  │
│  │  - Simulate fills  │  │
│  │  - Track positions │  │
│  └────────┬───────────┘  │
│           │              │
│  ┌────────▼───────────┐  │
│  │  Metrics Calculator│  │
│  │  - PnL, Sharpe     │  │
│  │  - Drawdown, WR    │  │
│  │  - Equity curve    │  │
│  └────────┬───────────┘  │
│           │              │
│  ┌────────▼───────────┐  │
│  │  Report Generator  │  │
│  │  - JSON results    │  │
│  │  - Trade log       │  │
│  │  - Artifacts       │  │
│  └────────────────────┘  │
└──────────────────────────┘
         │
         ▼
  Artifact Store (S3/MinIO)
  + DB update (status, metrics)
  + Real-time progress to dashboard
```

### 14.2 Backtest Types

**Type 1 — Trading Agent Backtest** (signal-driven):
1. Load historical messages from the configured data source (e.g., 2 years of Discord messages from #options-flow)
2. Replay messages in chronological order
3. For each message, the agent evaluates using its skills (same as live)
4. If agent says TAKE: simulate entry at historical price + configurable slippage
5. Apply exit rules: stop-loss, take-profit, time stop, analyst close signals
6. Record every decision and trade

**Type 2 — Strategy Agent Backtest** (heartbeat-driven):
1. Load historical OHLCV data for configured instruments
2. Simulate the heartbeat schedule (e.g., every 5 minutes)
3. At each tick, run the strategy logic
4. Simulate entries/exits at historical prices
5. Apply all position management rules

**Type 3 — Walk-Forward Backtest**:
1. Split historical data into in-sample (training) and out-of-sample (testing) windows
2. Optimize parameters on in-sample data
3. Validate on out-of-sample data
4. Repeat with rolling windows
5. Report both in-sample and out-of-sample performance

### 14.3 Metrics Calculated

| Metric | Formula/Description |
|---|---|
| Total PnL | Sum of all realized trades |
| Win Rate | Winning trades / total trades |
| Profit Factor | Gross profit / gross loss |
| Sharpe Ratio | (Annualized return - risk-free rate) / annualized volatility |
| Sortino Ratio | (Return - risk-free rate) / downside deviation |
| Max Drawdown | Largest peak-to-trough in equity curve |
| Average Win | Mean profit on winning trades |
| Average Loss | Mean loss on losing trades |
| Win/Loss Ratio | Average win / average loss |
| Expectancy | (Win rate x avg win) - (loss rate x avg loss) |
| Trade Count | Total number of trades |
| Average Hold Time | Mean duration of positions |
| Calmar Ratio | Annual return / max drawdown |
| Recovery Factor | Total PnL / max drawdown |
| Ulcer Index | Measure of downside volatility |

### 14.4 Approval Workflow

```
Backtest Complete
       │
       ▼
Dashboard displays results with pass/fail indicators
       │
       ├─ All metrics PASS → Green "Approve for Paper Trading" button
       │
       ├─ Some metrics FAIL → Yellow warning + "Approve with Caution" button
       │
       └─ Critical metrics FAIL (negative PnL, Sharpe < 0) → Red "Reject" button
       │
       ├─ Approve → Agent moves to PAPER_TRADING state
       │            Requires selecting a paper trading account
       │
       ├─ Reject → Agent moves to REJECTED state
       │           User can reconfigure and re-backtest
       │
       └─ Reconfigure → Edit agent config, auto re-backtest
```

---

## 15. Tech Stack & Reusable Components

### 15.1 Reusable Components from Existing Project (Phoenix v1)

The following components are carried over from the existing codebase with minimal modification:

**Frontend UI Primitives** (from `services/dashboard-ui/src/components/ui/`):

| Component | Source | Modifications |
|---|---|---|
| Button | `ui/button.tsx` | None — CVA variants work as-is |
| Card | `ui/card.tsx` | None |
| Dialog | `ui/dialog.tsx` | None |
| DropdownMenu | `ui/dropdown-menu.tsx` | None |
| Input | `ui/input.tsx` | None |
| Label | `ui/label.tsx` | None |
| Popover | `ui/popover.tsx` | None |
| ScrollArea | `ui/scroll-area.tsx` | None |
| Select | `ui/select.tsx` | None |
| Separator | `ui/separator.tsx` | None |
| Sheet | `ui/sheet.tsx` | None |
| Skeleton | `ui/skeleton.tsx` | None |
| Switch | `ui/switch.tsx` | None |
| Table | `ui/table.tsx` | None |
| Tabs | `ui/tabs.tsx` | None |
| Textarea | `ui/textarea.tsx` | None |
| Tooltip | `ui/tooltip.tsx` | None |
| Badge | `ui/badge.tsx` | Add new status variants |
| Avatar | `ui/avatar.tsx` | None |

**Frontend Shared Components**:

| Component | Source | Modifications |
|---|---|---|
| AppShell | `components/AppShell.tsx` | Update nav items for new tabs |
| ThemeProvider | `components/ThemeProvider.tsx` | None |
| TradingViewEmbed | `components/market-widgets/TradingViewEmbed.tsx` | None |
| WidgetWrapper | `components/market-widgets/WidgetWrapper.tsx` | None |
| TickerSearch | `components/market-widgets/TickerSearch.tsx` | None |
| RichTextEditor | `components/RichTextEditor.tsx` | None |

**Frontend Infrastructure**:

| Item | Source | Modifications |
|---|---|---|
| AuthContext | `context/AuthContext.tsx` | None |
| useAuth hook | `hooks/useAuth.ts` | None |
| cn() utility | `lib/utils.ts` | None |
| Vite config | `vite.config.ts` | Update proxy targets |
| Tailwind config | `tailwind.config.js` | Update theme tokens |
| CSS design tokens | `index.css` | Extend for new components |

**Backend Shared Libraries** (from `shared/`):

| Library | Source | Modifications |
|---|---|---|
| Broker Adapter | `shared/broker/adapter.py` | Add IBKR, Robinhood, Tradier adapters |
| Alpaca Adapter | `shared/broker/alpaca_adapter.py` | None |
| Circuit Breaker | `shared/broker/circuit_breaker.py` | None |
| Symbol Converter | `shared/broker/symbol_converter.py` | None |
| Kafka Producer | `shared/kafka_utils/producer.py` | None |
| Kafka Consumer | `shared/kafka_utils/consumer.py` | None |
| DLQ Handler | `shared/kafka_utils/dlq.py` | None |
| Credential Encryption | `shared/crypto/credentials.py` | None |
| Rate Limiter | `shared/rate_limiter.py` | None |
| Retry Logic | `shared/retry.py` | None |
| Graceful Shutdown | `shared/graceful_shutdown.py` | None |
| Metrics | `shared/metrics.py` | Extend for agent metrics |
| Deduplication | `shared/dedup.py` | None |
| Database Models | `shared/models/database.py` | Extend for new entities |
| Trade Model | `shared/models/trade.py` | Extend for agent context |
| NLP Sentiment | `shared/nlp/sentiment_classifier.py` | None |
| Ticker Extractor | `shared/nlp/ticker_extractor.py` | None |
| Market Calendar | `shared/market/calendar.py` | None |
| Discord Utils | `shared/discord_utils/channel_discovery.py` | None |
| Unusual Whales | `shared/unusual_whales/` | None |

**Backend Services** (carry over with modifications):

| Service | Source | Modifications |
|---|---|---|
| Auth Service | `services/auth-service/` | None |
| API Gateway | `services/api-gateway/` | Add v2 routes for agents, strategies, OpenClaw |
| Discord Ingestor | `services/discord-ingestor/` | Refactor to use Connector Framework interface |
| Trade Parser | `services/trade-parser/` | None (becomes a skill) |
| Trade Executor | `services/trade-executor/` | Refactor into Execution Service |
| Position Monitor | `services/position-monitor/` | Refactor into Monitoring Agent + Global Monitor |
| Reddit Ingestor | `services/reddit-ingestor/` | Refactor to use Connector Framework interface |

### 15.2 New Components (Phoenix v2)

**Frontend — New Pages**:

| Page | Description |
|---|---|
| TradesTab | Pipeline view of all trade signals |
| PositionsTab | Account-level position management |
| PerformanceTab | Analytics and metrics dashboard |
| AgentsTab | Trading agent management |
| AgentDetailPage | Agent backtesting/live detail |
| StrategyAgentsTab | Strategy agent management |
| ConnectorsTab | Connector configuration |
| SkillsAgentsConfigTab | Skill repo + agent config editor |
| AgentCreationWizard | Multi-step agent creation |
| MarketCommandCenter | Migrated from v1 — 50+ configurable market widgets |
| AdminTab | User management, API key vault, audit log |
| AgentNetworkViz | Interactive agent network graph (admin-only) |
| TaskBoardTab | Kanban task board with agent roles and automations |
| DevDashboard | Dev Agent activity, RL metrics, code changes (admin-only) |

**Frontend — New Components**:

| Component | Description |
|---|---|
| AgentCard | Flex card showing agent status, PnL, trades |
| AgentStatusBadge | Color-coded status indicator |
| BacktestProgressBar | Real-time backtest progress |
| BacktestResultsPanel | Metrics display with pass/fail indicators |
| TaskLog | Scrollable real-time log viewer (streamed from OpenClaw) |
| EquityCurveChart | Recharts LineChart for equity curves |
| PnLSparkline | Small inline chart for PnL trends |
| AgentHeatmap | Agent-Account performance matrix |
| ConnectorCard | Connector status and config card |
| SkillCard | Skill info with install/configure actions |
| TradeIntentTimeline | Visual timeline of a trade from signal to fill |
| MonitoringPanel | Real-time position monitoring dashboard |
| RiskGauge | Visual gauge for portfolio risk level |
| AgentNetworkGraph | @xyflow/react interactive graph of all instances and agents |
| ApiKeyVault | Secure credential management with masked inputs |
| AutomationCard | Cron-based automation config card |
| TaskKanbanBoard | Drag-and-drop kanban with @dnd-kit (reuse SprintBoard pattern) |
| RoleBadge | User role indicator with permission summary |
| SkillEditor | SKILL.md editor with syntax highlighting and live preview |
| BottomNavMobile | Mobile bottom navigation bar |

**Backend — New Services**:

| Service | Description |
|---|---|
| OpenClaw Bridge Service | REST API running alongside each OpenClaw instance for remote management |
| Orchestrator Worker | State machine for agent lifecycle and job management |
| Skill Sync Service | Centralized skill repo with push-to-instances |
| Backtest Service | Sandboxed backtest execution engine |
| Execution Service | Queue-based trade execution with risk checks |
| Global Position Monitor | Hard limits enforcement across all agents/accounts |
| Connector Manager | Unified connector lifecycle management |
| WebSocket Gateway | Real-time updates to dashboard (agent logs, positions, trades) |
| Automation Scheduler | Cron-based task execution engine for automations |
| Agent Communication Router | Routes inter-agent messages across instances via Event Bus |

### 15.3 Full Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| **Frontend** | React 18 + TypeScript + Vite 5 | Dashboard SPA |
| **UI Framework** | Tailwind CSS + Radix UI + Lucide Icons | Design system |
| **Charts** | Recharts + TradingView embeds | Visualizations |
| **Data Fetching** | TanStack React Query + Axios | API communication |
| **Real-Time** | WebSocket (native) + SSE | Live updates |
| **Backend API** | Python 3.12 + FastAPI + Uvicorn | REST API |
| **Database** | PostgreSQL 16 + SQLAlchemy 2 (async) | Persistent storage |
| **Time-Series** | TimescaleDB (PostgreSQL extension) | Market data, metrics |
| **Cache** | Redis 7 | Caching, sessions |
| **Job Queue** | Redis + BullMQ (Node.js workers) or Celery (Python) | Task queue |
| **Event Bus** | Redis Streams or NATS | Inter-service events |
| **Message Queue** | Apache Kafka (for high-volume data ingestion) | Data source ingestion |
| **Artifact Store** | MinIO (S3-compatible) | Backtest results, reports |
| **AI Runtime** | OpenClaw (Node.js) | Agent execution |
| **LLM Providers** | Claude (Anthropic) / GPT-4o (OpenAI) / Ollama (local) | Agent intelligence |
| **Backtesting** | VectorBT + custom engine in Docker | Strategy validation |
| **Broker SDK** | alpaca-py, robin_stocks, ib_insync | Order execution |
| **Market Data** | Polygon.io, Alpaca Data, Yahoo Finance | OHLCV and quotes |
| **Options Data** | Unusual Whales API | Flow, GEX, dark pool |
| **NLP** | FinBERT + spaCy | Sentiment classification |
| **Observability** | Prometheus + Grafana + Loki | Metrics, logs, dashboards |
| **Deployment** | Docker + k3s | Container orchestration |
| **VPS/Compute** | Hetzner / DigitalOcean / AWS | OpenClaw instances |
| **Agent Network Graph** | @xyflow/react | Agent network visualization |
| **Task Board** | @dnd-kit/core + @dnd-kit/sortable | Drag-and-drop kanban |

### 15.4 Mobile-Responsive Design

The dashboard is fully responsive and usable on mobile devices:

**Tailwind CSS Breakpoints**:
- `sm` (640px): single-column layouts, stacked cards
- `md` (768px): two-column layouts where applicable
- `lg` (1024px): full sidebar navigation
- `xl` (1280px): maximum width layouts with spacious grids

**Mobile Navigation**:
- Sidebar collapses to a hamburger menu (`Sheet` component from existing UI)
- Bottom navigation bar for primary tabs (Trades, Positions, Agents, Market)
- Swipe gestures on Task Board kanban columns

**Responsive Patterns**:
- Data tables → horizontal scroll on mobile, or switch to card view for key tables (positions, trades)
- Agent flex cards → single column grid on mobile
- Chart widgets → full-width with touch zoom/pan
- Dialogs → full-screen sheets on mobile (existing `Sheet` component)

**PWA Capability**:
- `manifest.json` for home screen install
- Service worker for offline caching of static assets
- Push notifications via service worker (for trade alerts when app is backgrounded)

---

## 16. Data Model

### 16.1 Core Entities

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ User             │     │ TradingAccount   │     │ OpenClawInstance │
├──────────────────┤     ├──────────────────┤     ├──────────────────┤
│ id               │     │ id               │     │ id               │
│ email            │1───*│ user_id          │     │ name             │
│ password_hash    │     │ broker_type      │     │ host             │
│ mfa_secret       │     │ mode (paper/live)│     │ port             │
│ role             │     │ credentials_enc  │     │ role             │
│ created_at       │     │ balance          │     │ status           │
└──────────────────┘     │ buying_power     │     │ agent_count      │
                         │ status           │     │ cpu_usage        │
                         └──────────────────┘     │ memory_usage     │
                                                  └──────────────────┘
```

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Agent            │     │ AgentBacktest    │     │ Skill            │
├──────────────────┤     ├──────────────────┤     ├──────────────────┤
│ id               │     │ id               │     │ id               │
│ name             │1───*│ agent_id         │     │ name             │
│ type (trading/   │     │ started_at       │     │ category         │
│       strategy)  │     │ completed_at     │     │ description      │
│ status           │     │ status           │     │ version          │
│ instance_id      │     │ total_signals    │     │ skill_md_content │
│ data_source_cfg  │     │ trades_taken     │     │ tools_required   │
│ skills[]         │     │ total_pnl        │     │ created_at       │
│ risk_config      │     │ win_rate         │     │ updated_at       │
│ monitor_agent_id │     │ sharpe_ratio     │     └──────────────────┘
│ account_id       │     │ max_drawdown     │
│ created_at       │     │ profit_factor    │
│ updated_at       │     │ equity_curve     │
└──────────────────┘     │ trade_log_url    │
                         │ artifacts_url    │
                         └──────────────────┘
```

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ TradeIntent      │     │ Position         │     │ Connector        │
├──────────────────┤     ├──────────────────┤     ├──────────────────┤
│ id               │     │ id               │     │ id               │
│ agent_id         │     │ account_id       │     │ type             │
│ ticker           │     │ agent_id         │     │ name             │
│ action (BUY/SELL)│     │ ticker           │     │ config_enc       │
│ instrument_type  │     │ side (long/short)│     │ status           │
│ quantity         │     │ quantity         │     │ assigned_agents[]│
│ price_target     │     │ entry_price      │     │ last_sync        │
│ stop_loss        │     │ current_price    │     │ created_at       │
│ take_profit      │     │ unrealized_pnl   │     └──────────────────┘
│ reasoning        │     │ stop_loss        │
│ source_message   │     │ take_profit      │
│ status           │     │ monitor_agent_id │
│ created_at       │     │ opened_at        │
│ filled_at        │     │ closed_at        │
│ fill_price       │     │ exit_price       │
│ broker_order_id  │     │ exit_reason      │
│ error            │     │ realized_pnl     │
└──────────────────┘     └──────────────────┘
```

```
┌──────────────────┐     ┌──────────────────┐
│ AgentLog         │     │ PerformanceMetric│
├──────────────────┤     ├──────────────────┤
│ id               │     │ id               │
│ agent_id         │     │ entity_type      │
│ timestamp        │     │ entity_id        │
│ level (info/     │     │ metric_type      │
│  warn/error)     │     │ value            │
│ message          │     │ period (daily/   │
│ context          │     │  weekly/monthly) │
│ session_id       │     │ date             │
└──────────────────┘     │ created_at       │
                         └──────────────────┘
```

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│ Task             │     │ Automation       │     │ DevIncident      │
├──────────────────┤     ├──────────────────┤     ├──────────────────┤
│ id               │     │ id               │     │ id               │
│ title            │     │ name             │     │ agent_id         │
│ description      │     │ cron_expression  │     │ issue_type       │
│ assigned_agent_id│     │ agent_role       │     │ severity         │
│ created_by       │     │ instance_id      │     │ diagnosis        │
│ (user or agent)  │     │ task_description │     │ action_taken     │
│ status           │     │ delivery_channel │     │ code_diff        │
│ priority         │     │ active           │     │ outcome          │
│ column           │     │ last_run         │     │ rl_reward        │
│ labels[]         │     │ next_run         │     │ status           │
│ due_date         │     │ created_at       │     │ created_at       │
│ output           │     └──────────────────┘     │ resolved_at      │
│ created_at       │                              └──────────────────┘
│ updated_at       │
└──────────────────┘

┌──────────────────┐     ┌──────────────────┐
│ AgentMessage     │     │ ApiKeyEntry      │
├──────────────────┤     ├──────────────────┤
│ id               │     │ id               │
│ from_agent_id    │     │ key_type         │
│ to_agent_id      │     │ name             │
│ intent           │     │ credentials_enc  │
│ data             │     │ status           │
│ response_to      │     │ last_used        │
│ timestamp        │     │ last_tested      │
└──────────────────┘     │ created_at       │
                         │ updated_at       │
                         └──────────────────┘
```

### 16.2 Key Relationships

- **User** 1:N **TradingAccount** — A user can have multiple broker accounts
- **User** 1:N **Agent** — A user creates and owns agents
- **Agent** 1:N **AgentBacktest** — Each agent can have multiple backtest runs
- **Agent** 1:1 **Agent** (monitor) — Every trading agent is paired with a monitoring agent
- **Agent** N:1 **OpenClawInstance** — Agents run on a specific instance
- **Agent** N:1 **TradingAccount** — An agent is assigned to one account for execution
- **Agent** N:N **Skill** — Agents use multiple skills, skills are shared across agents
- **Agent** 1:N **TradeIntent** — Agents generate trade intents
- **Agent** 1:N **Position** — Agents open positions (via execution service)
- **Connector** N:N **Agent** — Connectors feed data to multiple agents
- **Agent** 1:N **Task** — Agents can be assigned tasks and create their own
- **User** 1:N **Task** — Users create tasks for agents
- **Automation** N:1 **User** — Users configure automations
- **DevIncident** N:1 **Agent** — Dev Agent tracks incidents per agent
- **AgentMessage** N:N **Agent** — Agents communicate with each other
- **ApiKeyEntry** N:1 **User** — Users manage API credentials

---

## 17. Deployment & Code Cleanup

### 17.1 New Repository Structure

```
phoenix-v2/
├── apps/
│   ├── dashboard/              # React + TypeScript + Vite
│   │   ├── src/
│   │   │   ├── components/     # Reusable UI components (carried over)
│   │   │   │   ├── ui/         # Radix primitives
│   │   │   │   ├── agents/     # Agent cards, detail views
│   │   │   │   ├── charts/     # Recharts, TradingView
│   │   │   │   ├── connectors/ # Connector config UI
│   │   │   │   └── shared/     # AppShell, ThemeProvider, etc.
│   │   │   ├── pages/          # Tab pages
│   │   │   ├── hooks/          # Custom hooks
│   │   │   ├── context/        # Auth, Theme, WebSocket providers
│   │   │   ├── api/            # API client module (centralized)
│   │   │   └── types/          # TypeScript interfaces
│   │   ├── package.json
│   │   └── vite.config.ts
│   │
│   └── api/                    # FastAPI backend
│       ├── routes/
│       │   ├── auth.py
│       │   ├── agents.py
│       │   ├── strategies.py
│       │   ├── trades.py
│       │   ├── positions.py
│       │   ├── connectors.py
│       │   ├── skills.py
│       │   ├── instances.py
│       │   ├── backtests.py
│       │   ├── performance.py
│       │   └── ws.py           # WebSocket endpoints
│       ├── services/
│       ├── models/
│       └── main.py
│
├── services/
│   ├── orchestrator/           # Job queue worker + state machine
│   ├── execution/              # Trade execution service
│   ├── global-monitor/         # Portfolio-level risk monitor
│   ├── connector-manager/      # Connector lifecycle + ingestion
│   ├── backtest-runner/        # Sandboxed backtest execution
│   ├── skill-sync/             # Central skill repository sync
│   └── openclaw-bridge/        # REST API for OpenClaw instance management
│
├── shared/                     # Shared Python libraries (carried over + extended)
│   ├── broker/
│   ├── kafka_utils/
│   ├── models/
│   ├── nlp/
│   ├── crypto/
│   └── ...
│
├── skills/                     # Central skill repository
│   ├── data/                   # Data retrieval skills
│   ├── analysis/               # Analysis skills
│   ├── strategy/               # Strategy skills
│   ├── execution/              # Execution skills
│   ├── risk/                   # Risk & monitoring skills
│   ├── utility/                # Utility skills
│   └── advanced/               # AI/ML skills
│
├── openclaw/                   # OpenClaw instance templates
│   ├── strategy-lab/           # Instance A template
│   │   ├── AGENTS.md
│   │   ├── TOOLS.md
│   │   └── SOUL.md
│   ├── data-research/          # Instance B template
│   ├── promotion-risk/         # Instance C template
│   └── live-trading/           # Instance D template
│
├── infra/
│   ├── docker/
│   │   ├── Dockerfile.dashboard
│   │   ├── Dockerfile.api
│   │   ├── Dockerfile.orchestrator
│   │   ├── Dockerfile.execution
│   │   ├── Dockerfile.backtest-runner
│   │   └── ...
│   ├── docker-compose.yml      # Full stack
│   ├── docker-compose.dev.yml  # Development
│   └── k3s/
│       ├── docker-compose.k3s.yml
│       └── .env.production
│
├── migrations/                 # Alembic DB migrations
├── tests/
├── scripts/
├── .env.example
├── pyproject.toml
├── Makefile
└── README.md
```

### 17.2 k3s Deployment

**Dashboard + API** (primary k3s app):
- Docker Compose with: dashboard (nginx + React build), api (FastAPI), PostgreSQL, Redis, NATS/Redis Streams
- Exposed on custom domain (e.g., phoenix.yourdomain.com)
- HTTPS via k3s's built-in Let's Encrypt

**Supporting Services** (k3s services):
- Orchestrator Worker
- Execution Service
- Global Position Monitor
- Connector Manager
- Backtest Runner
- Skill Sync Service

**OpenClaw Instances** (separate VPS machines):
- Each instance runs on its own VPS (Hetzner/DigitalOcean)
- OpenClaw + Bridge Service installed via Docker or direct Node.js
- Connected to the central event bus via NATS or Redis Streams over WireGuard VPN
- Health monitored from the dashboard

**Infrastructure Services** (k3s or dedicated):
- MinIO (artifact store)
- TimescaleDB (time-series data)
- Kafka (if using for high-volume ingestion; otherwise Redis Streams suffices)
- Prometheus + Grafana (observability)

### 17.3 Environment Configuration

```env
# Database
DATABASE_URL=postgresql+asyncpg://phoenix:password@db:5432/phoenix_v2

# Redis
REDIS_URL=redis://redis:6379/0

# Event Bus
EVENT_BUS_TYPE=redis_streams  # or "nats"
NATS_URL=nats://nats:4222

# OpenClaw Instances
OC_INSTANCES=[
  {"id":"oc-strategy-lab","host":"10.0.1.10","port":18790},
  {"id":"oc-data-research","host":"10.0.1.11","port":18790},
  {"id":"oc-promotion-risk","host":"10.0.1.12","port":18790},
  {"id":"oc-live-trading","host":"10.0.1.13","port":18790}
]

# Skill Repository
SKILL_REPO_TYPE=s3  # or "git"
SKILL_REPO_URL=s3://phoenix-skills/

# Broker - Alpaca
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
ALPACA_BASE_URL=https://paper-api.alpaca.markets

# LLM
LLM_PROVIDER=anthropic  # or "openai", "ollama"
ANTHROPIC_API_KEY=...
LLM_MODEL_FAST=claude-3-5-haiku-20241022
LLM_MODEL_SMART=claude-sonnet-4-20250514

# Unusual Whales
UW_API_KEY=...

# JWT
JWT_SECRET=...
JWT_ALGORITHM=HS256
JWT_EXPIRY_MINUTES=60

# Artifact Store
MINIO_ENDPOINT=minio:9000
MINIO_ACCESS_KEY=...
MINIO_SECRET_KEY=...
MINIO_BUCKET=phoenix-artifacts
```

### 17.4 Deployment Sequence

1. **Provision infrastructure**: k3s server + 1-4 VPS for OpenClaw instances
2. **Set up WireGuard VPN**: Secure connectivity between k3s server and OpenClaw VPS nodes
3. **Deploy core services** on k3s: dashboard, API, PostgreSQL, Redis, NATS, MinIO
4. **Run migrations**: `alembic upgrade head`
5. **Deploy OpenClaw instances**: Install OpenClaw + Bridge Service on each VPS
6. **Register instances**: Via dashboard API or admin CLI
7. **Sync skills**: Push initial skill catalog to all instances
8. **Configure connectors**: Add Discord, Reddit, Unusual Whales, broker accounts via dashboard
9. **Create first agent**: Test the full lifecycle (create → backtest → review → paper trade)

### 17.5 Code Cleanup from Phoenix v1

When creating the new repository, the following services and code from the existing project should be handled:

**Services to Deprecate** (replaced by OpenClaw skills):

| Service | Replacement |
|---|---|
| `services/nlp-parser/` | OpenClaw skill: `sentiment-classifier`, `trade-signal-parser` |
| `services/sentiment-analyzer/` | OpenClaw skill: `sentiment-classifier`, `social-sentiment-analysis` |
| `services/news-aggregator/` | OpenClaw skill: `fetch-news-headlines`, `news-impact-analyzer` |
| `services/ai-trade-recommender/` | OpenClaw trading agents with evaluation skills |
| `services/signal-scorer/` | OpenClaw skill: `llm-trade-evaluator` |
| `services/option-chain-analyzer/` | OpenClaw skill: `options-chain-analyzer`, `options-greeks-analyzer` |
| `services/twitter-ingestor/` | Connector Framework: Twitter/X connector |

**Services to Keep and Refactor**:

| Service | Action |
|---|---|
| `services/auth-service/` | Keep as-is — handles JWT, MFA, email verification |
| `services/api-gateway/` | Refactor — add v2 routes for agents, strategies, OpenClaw, tasks, automations |
| `services/dashboard-ui/` | Rebuild — new pages/tabs, carry over UI primitives and reusable components |
| `services/discord-ingestor/` | Refactor into Connector Framework interface |
| `services/reddit-ingestor/` | Refactor into Connector Framework interface |
| `services/trade-executor/` | Refactor into Execution Service |
| `services/position-monitor/` | Replace with Monitoring Agent (OpenClaw) + Global Monitor (backend service) |
| `services/trade-parser/` | Convert to OpenClaw skill: `trade-signal-parser` |
| `services/notification-service/` | Expand — add Telegram, keep Discord, keep WhatsApp |
| `services/strategy-agent/` | Replace with OpenClaw Strategy Agents |

**Shared Libraries to Keep**:

| Library | Status |
|---|---|
| `shared/broker/` | Keep — adapter pattern, Alpaca, circuit breaker, symbol converter |
| `shared/crypto/` | Keep — Fernet encryption for API Key Vault |
| `shared/kafka_utils/` | Keep — producer, consumer, DLQ |
| `shared/market/calendar.py` | Keep — market hours, holidays |
| `shared/models/` | Extend — add new entities (Task, Automation, DevIncident, AgentMessage, ApiKeyEntry) |
| `shared/nlp/` | Keep — FinBERT sentiment, ticker extractor (also converted to skills) |
| `shared/discord_utils/` | Keep — channel discovery |
| `shared/unusual_whales/` | Keep — API integration |
| `shared/whatsapp/` | Keep — Meta Cloud API sender |
| `shared/retry.py`, `shared/dedup.py`, etc. | Keep — utility libraries |

**Files to Delete from Existing Repo**:
- All deprecated service directories listed above
- `shared/agents/` (replaced by OpenClaw agent framework)
- `shared/llm/client.py` (replaced by OpenClaw LLM integration)
- `services/source-orchestrator/` (replaced by Connector Manager)
- `services/audit-writer/` (replaced by centralized logging in new architecture)

---

## 18. Risk & Trade Execution Architecture

### 18.1 Execution Pipeline

The decision to use queue-based execution (agents push intents, execution service places orders) is final. Here is the complete pipeline:

```
Agent Decision: TAKE trade
         │
         ▼
┌──────────────────────────────┐
│  1. FORMAT TRADE INTENT      │
│  Agent uses skill:           │
│  format_trade_intent         │
│                              │
│  Output:                     │
│  {                           │
│    agent_id, ticker, action, │
│    qty, price, stop, target, │
│    reasoning, source_msg     │
│  }                           │
└──────────────┬───────────────┘
               │
         POST /api/v2/trade-intents
               │
               ▼
┌──────────────────────────────┐
│  2. VALIDATION               │
│  - Schema validation         │
│  - Agent is authorized       │
│  - Account is active         │
│  - Market hours check        │
│  - Deduplication check       │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  3. RISK CHECKS              │
│  - Position size within      │
│    agent limit               │
│  - Account daily loss not    │
│    exceeded                  │
│  - Max concurrent positions  │
│    not exceeded              │
│  - Correlated risk check     │
│  - Portfolio heat check      │
│  - Circuit breaker not       │
│    triggered                 │
└──────────────┬───────────────┘
               │
          ┌────┴────┐
          │ PASS?   │
          └────┬────┘
         YES   │    NO
          │    │     │
          │    │     ▼
          │    │  REJECT intent
          │    │  (log reason, notify agent)
          │    │
          ▼    │
┌──────────────────────────────┐
│  4. ORDER PLACEMENT          │
│  - Select broker adapter     │
│  - Place order via API       │
│  - Wait for fill/reject      │
│  - Record order ID           │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  5. POST-FILL                │
│  - Create Position record    │
│  - Assign monitoring agent   │
│  - Set stop-loss on broker   │
│    (backup hard stop)        │
│  - Notify dashboard (WS)     │
│  - Log to audit trail        │
└──────────────────────────────┘
```

### 18.2 Risk Hierarchy

Three layers of risk control, each operating independently:

**Layer 1 — Agent-Level Risk** (in OpenClaw):
- Configured per agent in risk_config
- Agent's LLM applies these when deciding TAKE/PASS
- Soft enforcement (agent can technically override, but training prevents it)

**Layer 2 — Execution Service Risk** (deterministic code):
- Hard-coded checks before every order
- Cannot be bypassed by any agent or user
- Rules:
  - Max position size per trade: configurable per agent
  - Max concurrent positions per agent: configurable
  - Max portfolio allocation per ticker: 10%
  - Daily loss limit per account: 5% (configurable)
  - Max portfolio heat: 25% (total risk across all positions)

**Layer 3 — Global Position Monitor** (independent service):
- Runs on a separate process, monitors all positions across all accounts
- Kill switch: if total portfolio drops 10% in one day, close everything and pause all agents
- Monitors for stuck orders, positions without monitoring agents, and orphaned trades
- Sends alerts (email, Discord, dashboard notification) for any anomaly

### 18.3 Circuit Breaker States

```
CLOSED (normal operation)
    │
    ├─ Daily loss < 3% → Stay CLOSED
    │
    ├─ Daily loss 3-5% → HALF_OPEN
    │   - Reduce max position sizes by 50%
    │   - Alert user
    │
    └─ Daily loss >= 5% → OPEN
        - No new trades allowed
        - Existing positions monitored with tighter stops
        - User must manually reset
        │
        └─ Daily loss >= 10% → EMERGENCY
            - Close ALL positions immediately
            - Pause ALL agents
            - Requires manual restart and acknowledgment
```

---

## 19. Appendix

### 19.1 Glossary

| Term | Definition |
|---|---|
| **OpenClaw** | Open-source AI agent runtime (Node.js) that runs locally and executes tasks via tools |
| **OpenClaw Instance** | A running OpenClaw process with its own workspace, agents, and configuration |
| **Agent** | An AI entity configured with a role, skills, and tools that performs specific tasks |
| **Trading Agent** | Agent that evaluates external signals and decides whether to trade |
| **Strategy Agent** | Agent that follows algorithmic rules on a heartbeat schedule |
| **Monitoring Agent** | Agent that watches positions and manages exits for a paired trading agent |
| **Skill** | A SKILL.md file that teaches an agent how to perform a specific task |
| **ClawHub** | OpenClaw's public skills marketplace (like npm for agent skills) |
| **Connector** | Integration with an external data source or broker API |
| **Trade Intent** | A structured request from an agent to the execution service to place a trade |
| **Backtest** | Simulation of an agent or strategy against historical data |
| **AGENTS.md** | OpenClaw config file defining agent identity, role, and behavior |
| **TOOLS.md** | OpenClaw config file defining which tools an agent can use |
| **HEARTBEAT.md** | OpenClaw config file for periodic scheduled tasks |
| **SOUL.md** | OpenClaw config file for agent personality and communication style |
| **Event Bus** | Redis Streams or NATS messaging system connecting all services |
| **Orchestrator** | Worker that manages agent lifecycle state machine and job execution |
| **Execution Service** | Service that validates, risk-checks, and places trade orders |
| **Artifact Store** | S3/MinIO storage for backtest results, reports, and code bundles |
| **Dev Agent** | Specialized agent that monitors all other agents, detects issues, auto-fixes code, and learns via RL |
| **Reinforcement Learning (RL)** | Machine learning approach where the Dev Agent learns optimal interventions from outcome feedback |
| **Task Board** | Kanban-style board where users create role-based agents and assign tasks |
| **Automation** | Scheduled recurring task (cron-based) that triggers an agent to execute a job and deliver results |
| **Agent-to-Agent Message** | Structured JSON message sent between agents for signal confirmation or collaboration |
| **Consensus Protocol** | Pattern where multiple agents confirm a signal before a trade is taken |
| **API Key Vault** | Encrypted credential store for all integration API keys and tokens |
| **Bridge Service** | REST API running alongside each OpenClaw instance for remote management by the dashboard |
| **PWA** | Progressive Web App — enables mobile home screen install and push notifications |
| **Agent Role** | Predefined template (Day Trader, Technical Analyst, etc.) for creating task-based agents |

### 19.2 API Endpoints (v2)

| Method | Endpoint | Description |
|---|---|---|
| **Agents** | | |
| POST | `/api/v2/agents` | Create new agent |
| GET | `/api/v2/agents` | List all agents |
| GET | `/api/v2/agents/:id` | Get agent details |
| PUT | `/api/v2/agents/:id` | Update agent config |
| DELETE | `/api/v2/agents/:id` | Delete agent |
| POST | `/api/v2/agents/:id/pause` | Pause agent |
| POST | `/api/v2/agents/:id/resume` | Resume agent |
| POST | `/api/v2/agents/:id/approve` | Approve for paper trading |
| POST | `/api/v2/agents/:id/promote` | Promote to live trading |
| GET | `/api/v2/agents/:id/logs` | Stream agent logs |
| **Backtests** | | |
| POST | `/api/v2/backtests` | Start backtest |
| GET | `/api/v2/backtests/:id` | Get backtest results |
| GET | `/api/v2/backtests/:id/trades` | Get backtest trade log |
| GET | `/api/v2/backtests/:id/equity-curve` | Get equity curve data |
| **Trades** | | |
| GET | `/api/v2/trades` | List all trade intents |
| GET | `/api/v2/trades/:id` | Get trade detail |
| POST | `/api/v2/trade-intents` | Submit trade intent (from agent) |
| **Positions** | | |
| GET | `/api/v2/positions` | List all positions |
| GET | `/api/v2/positions/open` | List open positions |
| POST | `/api/v2/positions/:id/close` | Manual close position |
| **Performance** | | |
| GET | `/api/v2/performance/accounts` | Account performance metrics |
| GET | `/api/v2/performance/agents` | Agent performance rankings |
| GET | `/api/v2/performance/sources` | Source performance |
| GET | `/api/v2/performance/daily` | Daily PnL summary |
| **Connectors** | | |
| POST | `/api/v2/connectors` | Create connector |
| GET | `/api/v2/connectors` | List connectors |
| PUT | `/api/v2/connectors/:id` | Update connector |
| DELETE | `/api/v2/connectors/:id` | Delete connector |
| POST | `/api/v2/connectors/:id/test` | Test connection |
| **OpenClaw Instances** | | |
| POST | `/api/v2/instances` | Register instance |
| GET | `/api/v2/instances` | List instances |
| GET | `/api/v2/instances/:id/health` | Instance health |
| POST | `/api/v2/instances/:id/sync-skills` | Trigger skill sync |
| **Skills** | | |
| POST | `/api/v2/skills` | Add skill to repo |
| GET | `/api/v2/skills` | List all skills |
| PUT | `/api/v2/skills/:id` | Update skill |
| DELETE | `/api/v2/skills/:id` | Remove skill |
| GET | `/api/v2/skills/clawhub/search` | Search ClawHub marketplace |
| POST | `/api/v2/skills/clawhub/install` | Install from ClawHub |
| **Strategies** | | |
| GET | `/api/v2/strategies/library` | List strategy templates |
| POST | `/api/v2/strategy-agents` | Create strategy agent |
| GET | `/api/v2/strategy-agents` | List strategy agents |
| GET | `/api/v2/strategy-agents/:id/heartbeat` | Get latest strategy state |
| **System** | | |
| GET | `/api/v2/system/health` | System health |
| POST | `/api/v2/system/kill-switch` | Emergency kill switch |
| GET | `/api/v2/system/circuit-breaker` | Circuit breaker status |
| **WebSocket** | | |
| WS | `/ws/agent-logs/:agent_id` | Stream agent activity logs |
| WS | `/ws/trades` | Real-time trade updates |
| WS | `/ws/positions` | Real-time position updates |
| WS | `/ws/backtest/:backtest_id` | Backtest progress stream |
| WS | `/ws/agent-network` | Agent network status updates |
| **Tasks** | | |
| POST | `/api/v2/tasks` | Create task (user or agent) |
| GET | `/api/v2/tasks` | List all tasks |
| GET | `/api/v2/tasks/:id` | Get task detail |
| PUT | `/api/v2/tasks/:id` | Update task |
| PATCH | `/api/v2/tasks/:id/move` | Move task between kanban columns |
| DELETE | `/api/v2/tasks/:id` | Delete task |
| **Automations** | | |
| POST | `/api/v2/automations` | Create automation |
| GET | `/api/v2/automations` | List automations |
| PUT | `/api/v2/automations/:id` | Update automation |
| DELETE | `/api/v2/automations/:id` | Delete automation |
| POST | `/api/v2/automations/:id/trigger` | Manually trigger automation |
| **Dev Agent** | | |
| GET | `/api/v2/dev-agent/incidents` | List all detected incidents |
| GET | `/api/v2/dev-agent/incidents/:id` | Get incident detail |
| GET | `/api/v2/dev-agent/code-changes` | List code changes made |
| POST | `/api/v2/dev-agent/code-changes/:id/rollback` | Rollback a code change |
| GET | `/api/v2/dev-agent/rl-metrics` | Get RL learning metrics |
| GET | `/api/v2/dev-agent/health-matrix` | Get all-agent health scores |
| **Agent Messages** | | |
| POST | `/api/v2/agent-messages` | Send inter-agent message |
| GET | `/api/v2/agent-messages` | List recent inter-agent messages |
| **Admin** | | |
| GET | `/api/v2/admin/users` | List all users |
| POST | `/api/v2/admin/users/:id/role` | Update user role |
| GET | `/api/v2/admin/roles` | List roles and permissions |
| PUT | `/api/v2/admin/roles/:id` | Update role permissions |
| GET | `/api/v2/admin/audit-log` | Get audit log entries |
| **API Key Vault** | | |
| POST | `/api/v2/vault/keys` | Add API key |
| GET | `/api/v2/vault/keys` | List keys (masked) |
| PUT | `/api/v2/vault/keys/:id` | Update key |
| DELETE | `/api/v2/vault/keys/:id` | Revoke key |
| POST | `/api/v2/vault/keys/:id/test` | Test key connection |

### 19.3 References

- [OpenClaw Documentation](https://docs.openclaw.ai) — Agent runtime, tools, skills, multi-agent routing
- [OpenClaw Multi-Agent Routing](https://docs.openclaw.ai/concepts/multi-agent) — Multi-agent architecture and message routing
- [ClawHub Skills Marketplace](https://github.com/openclaw/clawhub) — 3000+ community skills
- [OpenClaw Skills](https://docs.openclaw.ai/tools/skills) — Skill creation, SKILL.md format, precedence rules
- [OpenClaw Heartbeat](https://docs.openclaw.ai/gateway/heartbeat) — Periodic agent tasks and monitoring
- [OpenClaw Cron Jobs](https://docs.openclaw.ai/cron-jobs) — Scheduled tasks and automation
- [Alpaca Trading API](https://docs.alpaca.markets) — Paper + live trading, 1.5ms order processing
- [Unusual Whales API](https://docs.unusualwhales.com) — Options flow, GEX, dark pool data
- [NexusTrade: How to trade with AI the right way](https://nexustrade.io/blog/too-many-idiots-are-using-openclaw-to-trade-heres-how-to-trade-with-ai-the-right-way-20260203) — LLMs as strategy engineers, not discretionary traders
- [VectorBT](https://vectorbt.dev) — High-performance Python backtesting
- [Backtrader](https://www.backtrader.com) — Python backtesting framework
- [FinBERT](https://huggingface.co/ProsusAI/finbert) — Financial sentiment analysis model
- [TradingGrader](https://www.tradinggrader.com/features) — AI-driven trading performance grading
- [ICE Reddit Signals](https://ir.theice.com/press/news-details/2026/Intercontinental-Exchange-Launches-Reddit-Signals-and-Sentiment-Tool) — Reddit-to-market-signal data product
- [Self-Improving AI Agents: RL and Continual Learning](https://www.technology.org/2026/03/02/self-improving-ai-agents-reinforcement-continual-learning/) — RL for agent self-improvement
- [Reinforcement Learning for Self-Improving Agent with Skill Library](https://arxiv.org/html/2512.17102v1) — Agents evolving via RL and skill accumulation
- [AutoGen](https://microsoft.github.io/autogen/stable//index.html) — Microsoft's multi-agent orchestration framework
- [AI Multi-Agent Trading Dashboard System Design](/Users/projects/Downloads/AI%20Multi‑Agent%20Trading%20Dashboard%20System%20Design.pdf) — Comprehensive system design reference document

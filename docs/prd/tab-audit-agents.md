# AGENTS SECTION -- Deep Tab Audit

**Date:** 2026-04-11
**Auditor:** Nova (PM)
**Scope:** 10 tabs under the Agents section of the Phoenix Trade Bot dashboard (cashflow4us.com)

---

## Table of Contents

1. [Agents (/agents)](#1-agents-agents)
2. [Agent Dashboard (/agents/:id)](#2-agent-dashboard-agentsid)
3. [Agent Health (/agent-health)](#3-agent-health-agent-health)
4. [Strategies (/strategies)](#4-strategies-strategies)
5. [Skills (/skills)](#5-skills-skills)
6. [Backtests (/backtests)](#6-backtests-backtests)
7. [Agent Graph (/agent-graph)](#7-agent-graph-agent-graph)
8. [Morning Briefing (/morning-briefing)](#8-morning-briefing-morning-briefing)
9. [AutoResearch (/autoresearch)](#9-autoresearch-autoresearch)
10. [Phoenix Brain (/brain/wiki)](#10-phoenix-brain-brainwiki)

---

## 1. Agents (/agents)

**File:** `apps/dashboard/src/pages/Agents.tsx`

### Current State

**Components:**
- `AgentCard` -- Rich card per agent showing status strip, name/type, status badge, metric pills (P&L, Win Rate, Sharpe, Trades), mini equity curve, lifecycle actions
- `QuickSpawnTypedAgentButton` -- Dialog to spawn pre-built agents (Unusual Whales, Social Sentiment, Strategy, AutoResearch Supervisor)
- 4-step creation wizard: Channel > (optional Persona for analyst) > Risk Config > Review
- `StepChannel` -- Connector selection with Discord channel drill-down, multi-source for trend agents
- `StepPersona` -- PersonaSelector for analyst agents
- `StepRiskConfig` -- Slider inputs for max daily loss, max position size, stop loss, smart hold toggle
- `StepReview` -- Summary before creation
- `BacktestReviewDialog` -- Modal to review backtest results (equity curve, metrics, model comparison) with approve-to-paper/live actions
- `BacktestingSpinner` -- Progress indicator for agents currently backtesting
- Top-level MetricCards for agent stats (total, running, paused, backtesting, daily P&L)

**Data/API Endpoints:**
- `GET /api/v2/agents` -- Agent list
- `GET /api/v2/agent-stats` -- Summary stats
- `GET /api/v2/connectors` -- Available connectors
- `GET /api/v2/analyst/personas` -- Persona options
- `POST /api/v2/agents` -- Create agent (wizard submit)
- `POST /api/v2/agents/spawn-typed` -- Quick spawn pre-built agent
- `POST /api/v2/agents/:id/approve` -- Approve backtest with paper/live mode
- `POST /api/v2/agents/:id/pause`, `/resume`, `/delete`
- `POST /api/v2/agents/:id/retry-backtest` -- Retry failed backtest
- `GET /api/v2/agents/:id/backtest` -- Backtest data for review dialog
- `GET /api/v2/agents/:id/backtest-artifacts` -- Artifacts fallback
- `GET /api/v2/connectors?type=robinhood` -- Broker connectors for live approval

**Interactions:**
- Card click navigates to AgentDashboard
- Status-specific actions: Review & Approve (BACKTEST_COMPLETE), Promote to Live (PAPER/APPROVED), Pause/Resume/Delete (RUNNING/PAUSED)
- Error state shows billing error link and retry option
- Wizard enforces validation per step (connector + channel required for trading, persona required for analyst)

### Competitive Research

- **Alpaca**: Dashboard provides portfolio overview, trade entry widget, API management. Agent management via MCP server for natural language trading. No visual agent cards; API-first approach. ([source](https://alpaca.markets/learn/how-traders-are-using-ai-agents-to-create-trading-bots-with-alpaca))
- **QuantConnect**: Algorithm list with status (live/backtesting/stopped), one-click liquidation "kill switch", parameter sensitivity heatmaps, multi-asset support from single portfolio. ([source](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/algorithm-control))
- **MetaTrader 5**: Expert Advisor list in Navigator with trade permission toggles, on-chart dashboards for real-time parameter adjustment, built-in strategy tester with optimization. ([source](https://www.metatrader5.com/en/automated-trading))
- **AI-Trader (2026)**: Unified Dashboard as control center, collective intelligence where agents debate, instant agent integration. ([source](https://github.com/HKUDS/AI-Trader))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No bulk actions (pause all, delete multiple) | Medium | QuantConnect has bulk controls |
| No agent search/filter/sort on main page | High | With many agents, discoverability suffers |
| No drag-and-drop agent ordering or grouping | Low | Nice-to-have for power users |
| No agent cloning/templating from existing agent | Medium | QuantConnect allows algorithm cloning |
| No performance comparison view across agents | High | Alpaca/QC offer portfolio-level comparison |
| No agent versioning/rollback | Medium | QC tracks algorithm versions with git |
| Missing agent resource usage (CPU, memory, API cost) | Medium | MT5 shows resource consumption |
| No quick-toggle paper vs live per agent | Medium | QC has one-click mode switching |
| Wizard lacks preview of estimated backtest duration | Low | Sets user expectations |
| No agent marketplace or community templates | Low | MT5 has MQL5 marketplace |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Agent Search & Filter Bar** | Text search + status/type filter + sort (P&L, win rate, created) | Small | P0 | `Agents.tsx` |
| **Bulk Actions Toolbar** | Select multiple agents, batch pause/resume/delete | Medium | P1 | `Agents.tsx`, `agents.py` (API) |
| **Agent Comparison View** | Side-by-side metrics table for 2-4 selected agents | Medium | P1 | New component `AgentCompare.tsx` |
| **Clone Agent** | Duplicate agent config + rules to create variant | Small | P1 | `Agents.tsx`, `agents.py` |
| **Agent Cost Tracking** | Show Anthropic API credits consumed per agent per day | Medium | P2 | `Agents.tsx`, new API endpoint |
| **Agent Versioning** | Track config/rules snapshots with rollback | Large | P2 | DB migration, new API, `AgentDashboard.tsx` |

---

## 2. Agent Dashboard (/agents/:id)

**File:** `apps/dashboard/src/pages/AgentDashboard.tsx`

### Current State

**Top-level tabs:** Live | Backtesting (conditional on agent status)

**Live sub-tabs:**
- **Portfolio** -- MetricCards (Total P&L, Today P&L, Open Positions, Win Rate), cumulative P&L area chart, open positions list with 50%/Close actions, agent command mutations
- **Trades** -- 4 summary cards (Total P&L, Win Rate, Avg Hold, Total Trades), trade history with filters (All/Executed/Open/Rejected/Watchlisted), expandable trade rows with signal/reasoning/pattern details, DecisionTrailVisualizer per trade
- **Chat** -- Full chat interface with agent, thinking indicator, quick command buttons (Aggressive/Conservative/Pause/Resume), trade proposal approve/reject inline, ContextDebugger component
- **Intelligence** -- Model info (primary, accuracy, AUC-ROC), Analyst Profile, Learned Rules with weights, Top Predictive Features bar chart
- **Logs** -- Real-time log viewer with level filter (ALL/INFO/WARN/ERROR), text search, 5s polling
- **Rules** -- Editable trading rules (toggle/delete/add), risk parameter inputs, mode settings display, Pending Improvements section with backtest CI gate and activate/reject

**Backtesting sub-tabs:**
- **Overview** -- BacktestPipelineProgress (8-step progress bar with real-time logs), MetricsCards, EquityCurveChart, patterns display, ConsolidationPanel
- **Models** -- Sortable model comparison table (8 models, 9 metric columns), best model highlight
- **Features** -- Categorized feature browser (200+ features in 9 categories), preprocessing summary stats, search
- **Downloads** -- File list grouped by directory, Parquet-to-CSV conversion links

**Additional components loaded:** AgentMessagesTab, AgentScheduleTab, AgentTerminal, AgentSkillsTab, AgentWikiTab

**Data/API Endpoints:**
- `GET /api/v2/agents/:id` -- Agent detail
- `GET /api/v2/agents/:id/positions` -- Open positions (10s poll)
- `GET /api/v2/agents/:id/metrics/history` -- P&L curve
- `GET /api/v2/agents/:id/live-trades` -- Trade history (10s poll)
- `GET /api/v2/agents/:id/chat` -- Chat history (2-5s poll)
- `POST /api/v2/chat/send` -- Send chat message
- `POST /api/v2/agents/:id/command` -- Agent commands
- `GET /api/v2/agents/:id/manifest` -- Rules/risk/modes manifest
- `PUT /api/v2/agents/:id/manifest` -- Save rules/risk edits
- `GET /api/v2/agents/:id/logs` -- Agent logs
- `GET /api/v2/agents/:id/pending-improvements` -- Pending rule improvements
- `POST /api/v2/agents/:id/improvements/:id/run-backtest` -- CI backtest
- `POST /api/v2/agents/:id/pending-improvements/:id/approve` -- Activate rule
- `GET /api/v2/agents/:id/backtest-artifacts` -- Full backtest artifacts
- `GET /api/v2/agents/:id/backtest-csv/:name` -- CSV download
- WebSocket: `backtest-progress` channel for real-time updates

### Competitive Research

- **QuantConnect**: Live results page has Holdings, Trades, Logs, Runtime Statistics, Algorithm Control (kill switch, liquidate, add security, place trades). Parameter adjustment while live. ([source](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/algorithm-control))
- **TradeStation**: Real-time strategy performance with on-chart parameter tuning, Strategy Orders tab for order review/customization before execution. ([source](https://help.tradestation.com/10_00/eng/tradestationhelp/st_automation/strategy_automation.htm))
- **MetaTrader 5**: On-chart dashboard with live parameter adjustment without EA restart, ASQ PropGuard for prop firm rule monitoring. ([source](https://www.metatrader5.com/en/terminal/help/algotrading/trade_robots_indicators))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No real-time P&L ticker (websocket) | High | Only 10-30s polling; competitors show live ticks |
| No drawdown chart overlay | Medium | QC shows drawdown alongside equity |
| No trade P&L distribution histogram | Medium | Standard in quantitative platforms |
| No calendar heatmap of daily returns | Medium | Popular in QC and retail dashboards |
| Chat lacks markdown rendering | Medium | Agent responses are plain text |
| No "kill switch" emergency liquidation | High | QC has prominent Liquidate All button |
| No position-level P&L (unrealized) | High | Only entry price shown, no current price/unrealized |
| No trade journal/notes per trade | Low | Useful for learning |
| Rules tab lacks rule backtest preview | Medium | Cannot see impact of rule change before saving |
| No mobile-responsive trade actions | Medium | Position close buttons may be cramped on mobile |
| Intelligence tab has no trend over time | Medium | Shows snapshot, not how rules/accuracy evolved |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Emergency Liquidate All** | Prominent red button to close all positions immediately | Small | P0 | `AgentDashboard.tsx` (PortfolioTab), new API |
| **Real-time P&L via WebSocket** | Replace polling with WS push for positions and P&L | Medium | P0 | `use-websocket.ts`, `PortfolioTab` |
| **Unrealized P&L per Position** | Fetch current price, show unrealized gain/loss per position | Medium | P0 | `PortfolioTab`, pricing API |
| **Drawdown Chart** | Overlay drawdown percentage on equity curve | Small | P1 | `PortfolioTab`, `AreaChart` |
| **Trade P&L Distribution** | Histogram of trade outcomes (win/loss buckets) | Small | P1 | New component in `TradesTab` |
| **Calendar Heatmap** | Daily returns heatmap (GitHub-contribution style) | Medium | P1 | New component `CalendarHeatmap.tsx` |
| **Chat Markdown Rendering** | Render agent messages with markdown (react-markdown) | Small | P1 | `ChatTab` |
| **Rule Impact Preview** | "What-if" simulation when toggling/adding rules | Large | P2 | `RulesTab`, new backtest-lite API |

---

## 3. Agent Health (/agent-health)

**File:** `apps/dashboard/src/pages/AgentHealth.tsx`

### Current State

**Components:**
- Top MetricCards: Total Agents, Healthy, Warning, Error
- `AgentHealthCard` -- Per-agent card with health bar (green/amber/red), uptime, last heartbeat (stale = red), today trades, today P&L, error count (24h), actions (Pause/Start/Restart/View)
- Error log table with expandable stack traces, filterable by agent name or message
- Health computed from status + heartbeat freshness (>5 min = warning)

**Data/API Endpoints:**
- `GET /api/v2/agents` -- All agents with health fields (30s poll)
- `GET /api/v2/system-logs?source=agent&level=ERROR&limit=50` -- Error logs (30s poll)
- `POST /api/v2/agents/:id/restart` -- Restart agent
- `POST /api/v2/agents/:id/pause` -- Pause agent

### Competitive Research

- **QuantConnect**: No dedicated health page; health embedded in live results. Kill switch for emergency.
- **MetaTrader 5**: Navigator shows running EAs with trade permission icons, no centralized health dashboard.
- **Industry best practice**: Centralized health dashboards with SLA metrics, uptime tracking, alert rules, incident timeline. AI agent dashboard platforms (2026) emphasize real-time monitoring with anomaly detection and auto-recovery. ([source](https://thecrunch.io/ai-agent-dashboard/))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No historical health timeline (uptime chart per agent) | Medium | Only shows current snapshot |
| No alerting/notification rules (email/SMS/Discord when agent goes unhealthy) | High | Critical for live trading |
| No auto-recovery actions (auto-restart on crash) | Medium | Only manual restart available |
| No resource metrics (CPU, memory, API call rate) | Medium | Useful for debugging performance |
| No SLA/uptime percentage calculation | Low | Nice for tracking reliability |
| Error log lacks severity trending (are errors increasing?) | Medium | No sparkline or trend indicator |
| No correlation between health events and P&L impact | Medium | Hard to assess blast radius |
| 30s polling is slow for health monitoring | Medium | Should be 5-10s or WebSocket |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Health Alerts** | Configurable alerts (webhook/Discord/email) when agent health degrades | Large | P0 | New `AlertConfig` component, backend alert service |
| **Uptime Timeline** | Per-agent 24h/7d health sparkline showing up/down periods | Medium | P1 | `AgentHealthCard`, new API endpoint |
| **Auto-Recovery Policy** | Auto-restart agents after N consecutive health failures | Medium | P1 | Backend service, `AgentHealthCard` toggle |
| **Error Trend Sparkline** | Mini chart showing error rate over last 24h | Small | P2 | `AgentHealth.tsx` top metrics |
| **Health <> P&L Correlation** | Show P&L impact during unhealthy periods | Medium | P2 | New analysis component |

---

## 4. Strategies (/strategies)

**File:** `apps/dashboard/src/pages/Strategies.tsx`

### Current State

**Components:**
- `AgentLeaderboardTable` -- Ranked leaderboard of strategies by P&L (sidebar)
- `StrategyCard` -- Card per strategy with P&L, Win Rate, Sharpe, Max DD, Total Trades
- 4-step creation wizard: Select Strategy (50 templates) > Configure (rules, backtest params, skills, AI role description) > Instance (OpenClaw) > Review
- `TemplateCard` -- Template selector with AI suitability badge, win rate estimate, risk profile
- `WizardStep2` -- Config editor with dynamic fields from template defaults, skill toggles, AiAssistPopover for role description
- Categories with counts, search filter

**Data/API Endpoints:**
- `GET /api/v2/strategies` -- Strategy list
- `GET /api/v2/strategies/templates` -- 50 template catalog with categories
- `GET /api/v2/instances` -- OpenClaw instances
- `POST /api/v2/strategies` -- Create strategy + start backtest

### Competitive Research

- **QuantConnect**: Strategy library with community contributions, parameter optimization via heatmaps, multi-asset universe selection, walk-forward optimization. ([source](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview))
- **TradeStation**: EasyLanguage strategy builder, RadarScreen for real-time scanning, decades of historical data for backtesting. ([source](https://kjtradingsystems.com/tradestation.html))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No strategy performance over time (P&L evolution chart) | Medium | Only snapshot metrics |
| No strategy comparison side-by-side | Medium | Leaderboard ranks but cannot compare details |
| No parameter optimization / sensitivity analysis | High | QC's killer feature |
| No walk-forward testing option | Medium | Industry standard for robustness |
| No strategy marketplace / sharing | Low | QC has community library |
| No strategy-level risk analytics (VaR, CVaR) | Medium | Standard in quant platforms |
| Leaderboard only ranks by P&L, not risk-adjusted | Medium | Sharpe ranking option needed |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Leaderboard Sort Options** | Sort by Sharpe, Win Rate, Max DD, not just P&L | Small | P0 | `Strategies.tsx`, `AgentLeaderboardTable` |
| **Strategy Equity Curve** | Mini chart per strategy card showing P&L evolution | Medium | P1 | `StrategyCard`, new API |
| **Parameter Optimization** | Grid search or Bayesian optimization with heatmap visualization | Large | P1 | New page/modal, backend optimizer |
| **Strategy Comparison** | Select 2-3 strategies for detailed side-by-side | Medium | P2 | New component |
| **Risk Analytics** | VaR, CVaR, Sortino ratio per strategy | Medium | P2 | Backend calculation, `StrategyCard` |

---

## 5. Skills (/skills)

**File:** `apps/dashboard/src/pages/Skills.tsx`

### Current State

**Components:**
- Two tabs: Skill Catalog | Agent Configuration
- Skill Catalog: Category dropdown filter (analysis/data/execution/risk/all), skill cards with name, category badge, description, click-to-open side panel
- Agent Configuration: Read-only display of AGENTS.md, SOUL.md, TOOLS.md in pre-formatted blocks
- Sync Skills button to discover skills from agents
- `SidePanel` for skill detail (minimal -- just description + category badge)

**Data/API Endpoints:**
- `GET /api/v2/skills?category=<cat>` -- Skills filtered by category
- `GET /api/v2/skills/agent-config` -- Agent markdown configs
- `POST /api/v2/skills/sync` -- Trigger skill discovery

### Competitive Research

- **QuantConnect**: Modular Algorithm Framework with Alpha, Risk Management, Portfolio Construction, and Execution modules that can be mixed and matched. ([source](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview))
- **MetaTrader 5**: MQL5 Code Base with thousands of downloadable indicators, scripts, and EAs. Market for buying/selling. ([source](https://www.mql5.com/en/code/mt5))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Skill detail panel is very sparse (just description) | Medium | No usage stats, no code preview, no dependency info |
| No skill-to-agent mapping (which agents use which skills) | High | Critical for understanding agent capabilities |
| Agent Configuration tab is read-only with no editing | Medium | Should allow editing CLAUDE.md |
| No skill versioning or changelog | Low | Important for tracking skill evolution |
| No skill performance metrics | Medium | Which skills contribute most to alpha? |
| No skill marketplace / custom skill creation UI | Low | Power user feature |
| No search within skill catalog | Medium | Category filter alone is insufficient |
| Side panel has no "assign to agent" action | Medium | Workflow gap |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Skill-Agent Matrix** | Show which agents use each skill, and vice versa | Medium | P0 | `Skills.tsx`, new API endpoint |
| **Skill Detail Enrichment** | Usage count, last invoked, avg execution time, success rate | Medium | P1 | `SidePanel` content, new API |
| **Skill Search** | Text search across skill names and descriptions | Small | P1 | `Skills.tsx` |
| **Agent Config Editor** | Editable CLAUDE.md/SOUL.md with save and agent restart | Medium | P2 | `Skills.tsx` Agent Configuration tab |
| **Assign Skill to Agent** | Action button in skill panel to attach skill to selected agent | Medium | P2 | `SidePanel`, API endpoint |

---

## 6. Backtests (/backtests)

**File:** `apps/dashboard/src/pages/Backtests.tsx`

### Current State

**Components:**
- Summary cards: Total Runs, Running, Completed, Failed
- Left panel: Run list with agent name, status badge (RUNNING/COMPLETED/FAILED/PENDING), trade count, win rate, Sharpe, timestamp
- Right panel (detail): Pipeline Progress visualization (9 steps: Transform > Enrich > Embed > Preprocess > Train > Evaluate > Explain > Patterns > Create Agent), metrics grid (Trades, Win Rate, Sharpe, Return), live log viewer with color-coded levels, error message display
- WebSocket real-time updates via `useRealtimeQuery` on `backtest-progress` channel
- Fallback 30s polling for backtest list, 15s for logs

**Data/API Endpoints:**
- `GET /api/v2/backtests` -- All backtest runs
- `GET /api/v2/agents` -- Agent names for display
- `GET /api/v2/system-logs?backtest_id=<id>&limit=200` -- Backtest logs

### Competitive Research

- **QuantConnect**: Extensive backtesting with walk-forward, parameter optimization heatmaps, out-of-sample testing, multi-asset support, decades of tick data. Cloud compute for parallelization. ([source](https://www.quantconnect.com/))
- **TradeStation**: Strategy backtesting against decades of historical data, real-time SA performance monitoring. ([source](https://help.tradestation.com/10_00/eng/tradestationhelp/st_automation/trade_strategy.htm))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No way to launch a new backtest from this page | High | Must go through Agents or Strategies |
| No backtest comparison (side-by-side runs) | Medium | QC allows comparing iterations |
| No equity curve in backtest detail | Medium | Only available in AgentDashboard |
| No parameter sensitivity visualization | High | QC's heatmaps are industry-leading |
| Pipeline progress is log-based, not progress-percentage-based | Low | Works but imprecise |
| No backtest queue management (cancel, reorder) | Medium | Useful with multiple running backtests |
| No historical backtest archiving/search | Low | List grows unbounded |
| Missing backtest duration/estimated time remaining | Medium | User has no time expectation |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Launch Backtest Button** | "New Backtest" action to select agent + parameters | Medium | P0 | `Backtests.tsx`, new dialog |
| **Equity Curve in Detail** | Show equity curve chart alongside metrics in detail panel | Small | P1 | `Backtests.tsx` detail panel |
| **Backtest Comparison** | Select 2+ runs, show metrics side-by-side | Medium | P1 | New component |
| **Cancel Running Backtest** | Ability to abort a running backtest | Small | P1 | `Backtests.tsx`, API endpoint |
| **ETA / Duration Display** | Show elapsed time and estimated completion | Small | P2 | `Backtests.tsx` run list |
| **Parameter Heatmaps** | Optimization sweep with visual heatmap output | Large | P2 | New page, backend optimizer |

---

## 7. Agent Graph (/agent-graph)

**File:** `apps/dashboard/src/pages/AgentGraph.tsx`

### Current State

**Components:**
- ReactFlow interactive graph with custom `AgentNodeContent` nodes
- Nodes show: agent name, status (color-coded dot + badge), character type, win rate, total trades, channel subscriptions
- Edges: animated arrows between agents with message count labels, thickness proportional to message volume
- MiniMap, Controls (zoom/fit), Background grid
- Top metrics: Live Agents, Paper Agents, Active Links (24h)
- Status legend with 6 colors (live, paper, backtesting, approved, pending, error)
- Node click navigates to AgentDashboard
- Layout: grid-based auto-layout (sqrt columns)

**Data/API Endpoints:**
- `GET /api/v2/agents/graph` -- Returns `{ nodes: AgentNode[], edges: AgentEdge[] }` with agent metadata and inter-agent communication links
- 15s polling refresh

### Competitive Research

- **AI-Trader (2026)**: Collective intelligence where agents collaborate and debate, visualized as a network. ([source](https://github.com/HKUDS/AI-Trader))
- **Industry**: Multi-agent orchestration platforms show dependency graphs, message flow, and bottleneck detection. AI agent dashboards emphasize topology visualization with real-time status. ([source](https://thecrunch.io/ai-agent-dashboard/))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Auto-layout is simple grid; no hierarchy or force-directed layout | Medium | Supervisor > trader > monitor hierarchy not visible |
| No edge filtering (by type, time range) | Low | Gets cluttered with many agents |
| No real-time message flow animation | Medium | Would show live inter-agent communication |
| No agent group/cluster visualization | Medium | Cannot see which agents form a trading team |
| Node detail is minimal (no P&L on hover) | Low | Must click through to dashboard |
| No graph search/highlight | Low | Hard to find specific agent visually |
| Cannot create agents or connections from graph | Low | View-only |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Hierarchical Layout** | Dagre/ELK layout to show supervisor > agent > monitor tree | Medium | P1 | `AgentGraph.tsx`, layout algorithm |
| **Agent Cluster Groups** | Visual grouping of related agents (same strategy, same channel) | Medium | P1 | `AgentGraph.tsx`, group nodes |
| **Tooltip with P&L** | Hover on node shows P&L, win rate, last trade without clicking | Small | P1 | `AgentNodeContent` |
| **Live Message Flow** | Animated particles along edges when agents communicate | Medium | P2 | Custom edge component |
| **Graph Filter Panel** | Filter by status, agent type, time range for edges | Small | P2 | `AgentGraph.tsx` |

---

## 8. Morning Briefing (/morning-briefing)

**File:** `apps/dashboard/src/pages/MorningBriefing.tsx`

### Current State

**Components:**
- Header with "Run Now" button to manually trigger briefing
- Scheduler status card: running indicator, next morning briefing time, all scheduled jobs list
- Latest briefing card: agents woken count, dispatched channels, title, body (pre-formatted text), timestamp, click to navigate to /briefings history
- Spawn confirmation card: shows task_key and auto-refresh notice

**Data/API Endpoints:**
- `agentsApi.schedulerStatus()` -- Scheduler status
- `GET /api/v2/briefings?kind=morning&limit=1` -- Latest morning briefing (5s poll)
- `agentsApi.triggerMorningBriefing()` -- Manual trigger

### Competitive Research

- **Industry**: Pre-market briefings are a premium feature in AI trading platforms. Trade Ideas and Tickeron offer AI-generated market scans. Best-in-class platforms include economic calendar integration, earnings previews, sector rotation analysis, and overnight news impact assessment. ([source](https://www.pragmaticcoders.com/blog/top-ai-tools-for-traders))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Styling uses raw Tailwind (bg-gray-800) not design system components | Medium | Inconsistent with rest of dashboard |
| Briefing body is plain pre-formatted text, not structured | High | Should parse into sections (macro, sectors, watchlist) |
| No briefing history on this page (must click to /briefings) | Medium | Should show last 5-7 inline |
| No economic calendar or earnings schedule integration | Medium | Key for pre-market context |
| No customization of briefing content/sections | Medium | Users want to configure what they see |
| No agent action summary (what each agent plans to do today) | Medium | Briefing wakes agents but does not show their intentions |
| No market data widgets (futures, pre-market movers) | High | Standard for morning briefing pages |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Design System Migration** | Replace raw gray-800 classes with Card/Badge/Button components | Small | P0 | `MorningBriefing.tsx` |
| **Structured Briefing Layout** | Parse briefing body into sections with headers, icons, collapsible areas | Medium | P0 | `MorningBriefing.tsx` |
| **Market Data Widgets** | Pre-market futures, overnight movers, VIX, key levels | Medium | P1 | New component, market data API |
| **Briefing History Inline** | Show last 7 briefings in a collapsible timeline below latest | Small | P1 | `MorningBriefing.tsx` |
| **Economic Calendar** | Upcoming events (FOMC, CPI, earnings) with impact rating | Medium | P2 | New component, FRED/earnings API |
| **Agent Day Plan** | Per-agent summary of watchlist and planned actions | Medium | P2 | New API endpoint, component |

---

## 9. AutoResearch (/autoresearch)

**File:** `apps/dashboard/src/pages/AutoResearch.tsx`

### Current State

**Components:**
- Manual trigger buttons: "Run Supervisor Now" and "Run EOD Analysis Now"
- Scheduler info: next run times for supervisor (16:30 ET) and EOD analysis (16:45 ET)
- Trade Signal Stats: 30-day breakdown by decision type (count + missed opportunities)
- Total Missed Opportunities counter (RL feedback candidates)
- Latest EOD Summary: timestamp + body text
- Raw JSON display for supervisor/EOD results

**Data/API Endpoints:**
- `agentsApi.schedulerStatus()` -- Scheduler status
- `agentsApi.tradeSignalStats(undefined, 30)` -- 30-day signal stats
- `agentsApi.latestEodSummary()` -- Latest EOD analysis
- `agentsApi.triggerSupervisor()` -- Manual supervisor run
- `agentsApi.triggerEodAnalysis()` -- Manual EOD run

### Competitive Research

- **QuantConnect**: Alpha Streams marketplace where algorithms compete and are ranked by live performance. Institutional investors can license top algorithms. ([source](https://www.quantconnect.com/))
- **AI-Trader**: Continuous improvement loop where agents learn from each other's trades. ([source](https://github.com/HKUDS/AI-Trader))
- **Tickeron**: High-frequency AI agents with 5-min and 15-min intervals, rapid iteration on strategy adjustments. ([source](https://tickeron.com/trading-investing-101/top-ai-trading-platforms-transforming-modern-markets/))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Styling uses raw Tailwind, inconsistent with design system | Medium | Same issue as Morning Briefing |
| Raw JSON dump for results is not user-friendly | High | Should be structured cards/tables |
| No improvement history/timeline | High | Cannot see what improvements were proposed over time |
| No A/B test tracking (old rules vs new rules) | Medium | Karpathy-style needs experiment tracking |
| No missed opportunity detail view | Medium | Counts shown but cannot drill into specific missed trades |
| No learning curve visualization (is the system getting better?) | High | Core value prop of AutoResearch |
| No agent-level improvement breakdown | Medium | Which agent improved most? |
| No experiment configuration (cannot adjust what supervisor optimizes) | Medium | Hardcoded optimization goals |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Design System Migration** | Replace raw styling with Card/Badge/MetricCard components | Small | P0 | `AutoResearch.tsx` |
| **Improvement Timeline** | Chronological list of all proposed improvements with status (applied/rejected/pending) | Medium | P0 | `AutoResearch.tsx`, new API |
| **Learning Curve Chart** | Line chart showing agent performance evolution over weeks/months | Medium | P1 | New component, metrics history API |
| **Missed Opportunity Drill-down** | Click missed count to see specific signals that should have been traded | Medium | P1 | New detail panel |
| **Experiment Tracker** | A/B comparison of before/after improvement metrics | Large | P2 | New component, backend tracking |
| **Supervisor Config** | UI to set optimization goals, constraints, and frequency | Medium | P2 | New settings panel |

---

## 10. Phoenix Brain (/brain/wiki)

**File:** `apps/dashboard/src/pages/BrainWikiPage.tsx`

### Current State

**Components:**
- Header with total entry count
- Filter bar: text search, category dropdown (8 categories: Trade Observation, Market Pattern, Strategy Learning, Risk Note, Sector Insight, Indicator Note, Earnings Playbook, General), confidence slider (0-100%)
- `BrainEntryCard` -- Card per entry with title, author agent, category badge, confidence badge (color-coded), expandable content, symbols (up to 4), tags (up to 4), date
- Skeleton loading grid, empty state
- Debounced search (300ms)

**Data/API Endpoints:**
- `GET /api/v2/brain/wiki?per_page=50&min_confidence=<n>&category=<cat>&search=<q>` -- Paginated wiki entries

### Competitive Research

- **AI-Trader**: Collective intelligence where agents share and debate insights. Knowledge flows between agents to improve consensus. ([source](https://github.com/HKUDS/AI-Trader))
- **Industry**: Knowledge management in trading typically involves structured trade journals, pattern libraries, and shared playbooks. Best practices emphasize searchable, version-controlled, attribution-tracked knowledge bases. ([source](https://www.pragmaticcoders.com/blog/top-ai-tools-for-traders))

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Read-only; no way to add/edit entries manually | Medium | Users may want to contribute knowledge |
| No pagination controls (loads 50 entries) | Medium | Will not scale with hundreds of entries |
| No entry detail page (only expand/collapse in card) | Low | Long entries are cramped |
| No knowledge graph visualization (related entries) | Medium | Would show connections between insights |
| No entry validation/voting (is this knowledge still accurate?) | Medium | Knowledge can become stale |
| No export/download of knowledge base | Low | Useful for backup or external analysis |
| Debounce implementation is naive (setTimeout without cleanup) | Low | Can cause race conditions |
| No sorting options (only filtered by search/category/confidence) | Medium | Cannot sort by recency, confidence, or popularity |
| No entry versioning (shows version field but no history) | Low | Version field exists but unused in UI |

### Implementation Proposals

| Feature | Description | Complexity | Priority | Key Files |
|---------|-------------|------------|----------|-----------|
| **Pagination Controls** | Page navigation or infinite scroll for large knowledge bases | Small | P0 | `BrainWikiPage.tsx` |
| **Sort Options** | Sort by date, confidence, category, agent | Small | P0 | `BrainWikiPage.tsx` |
| **Manual Entry Creation** | Form to add human-contributed knowledge entries | Medium | P1 | `BrainWikiPage.tsx`, new dialog, API endpoint |
| **Entry Voting/Validation** | Thumbs up/down or "still accurate" flag per entry | Medium | P1 | `BrainEntryCard`, API endpoint |
| **Knowledge Graph View** | D3/ReactFlow visualization of related entries by symbol/tag | Large | P2 | New component |
| **Fix Debounce** | Replace naive setTimeout with proper useDebounce hook | Small | P2 | `BrainWikiPage.tsx` |

---

## Cross-Cutting Issues

These issues affect multiple tabs and should be addressed holistically:

| Issue | Affected Tabs | Priority |
|-------|--------------|----------|
| **Inconsistent styling** -- Morning Briefing and AutoResearch use raw Tailwind (bg-gray-800) instead of design system components | 8, 9 | P0 |
| **No global agent search** -- Cannot find a specific agent quickly across the platform | 1, 3, 7 | P0 |
| **Polling-heavy architecture** -- Most tabs use 5-30s polling; should migrate to WebSocket for real-time data | 1, 2, 3, 6 | P1 |
| **No mobile optimization** -- Agent cards and tables are not optimized for small screens | All | P1 |
| **No dark/light mode consistency** -- Some components hardcode dark theme colors | 8, 9 | P1 |
| **No unified notification system** -- Health alerts, trade notifications, briefing alerts are all separate or missing | 3, 8 | P1 |
| **No data export** -- Cannot export trades, metrics, or knowledge to CSV/PDF | 2, 10 | P2 |

---

## Priority Summary

### P0 (Critical -- Do Now)
1. Agent Search & Filter Bar (Tab 1)
2. Emergency Liquidate All button (Tab 2)
3. Real-time P&L via WebSocket (Tab 2)
4. Unrealized P&L per Position (Tab 2)
5. Health Alerts/Notifications (Tab 3)
6. Design System Migration for Morning Briefing + AutoResearch (Tabs 8, 9)
7. Structured Briefing Layout (Tab 8)
8. Improvement Timeline (Tab 9)
9. Pagination + Sort for Brain Wiki (Tab 10)
10. Launch Backtest from Backtests page (Tab 6)
11. Leaderboard Sort Options (Tab 4)

### P1 (Important -- Next Sprint)
1. Bulk Actions Toolbar (Tab 1)
2. Agent Comparison View (Tab 1)
3. Clone Agent (Tab 1)
4. Drawdown Chart + Trade P&L Distribution + Calendar Heatmap (Tab 2)
5. Chat Markdown Rendering (Tab 2)
6. Uptime Timeline + Auto-Recovery (Tab 3)
7. Strategy Equity Curve + Parameter Optimization (Tab 4)
8. Skill-Agent Matrix + Skill Detail Enrichment + Search (Tab 5)
9. Equity Curve in Backtest Detail + Comparison + Cancel (Tab 6)
10. Hierarchical Layout + Clusters + Tooltip (Tab 7)
11. Market Data Widgets + Briefing History (Tab 8)
12. Learning Curve Chart + Missed Opportunity Drill-down (Tab 9)
13. Manual Entry Creation + Voting (Tab 10)

### P2 (Nice to Have -- Backlog)
1. Agent Cost Tracking + Versioning (Tab 1)
2. Rule Impact Preview (Tab 2)
3. Error Trend Sparkline + Health<>P&L Correlation (Tab 3)
4. Strategy Comparison + Risk Analytics (Tab 4)
5. Agent Config Editor + Assign Skill (Tab 5)
6. ETA Display + Parameter Heatmaps (Tab 6)
7. Live Message Flow + Graph Filters (Tab 7)
8. Economic Calendar + Agent Day Plan (Tab 8)
9. Experiment Tracker + Supervisor Config (Tab 9)
10. Knowledge Graph View + Fix Debounce (Tab 10)

---

## Research Sources

- [Alpaca MCP Server and AI Agent Integration](https://alpaca.markets/learn/how-traders-are-using-ai-agents-to-create-trading-bots-with-alpaca)
- [Alpaca Dashboard Review](https://tradingfinder.com/brokers/alpaca-markets/dashboard/)
- [QuantConnect Algorithm Control](https://www.quantconnect.com/docs/v2/cloud-platform/live-trading/algorithm-control)
- [QuantConnect Algorithm Framework](https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/overview)
- [MetaTrader 5 Automated Trading](https://www.metatrader5.com/en/automated-trading)
- [MetaTrader 5 Expert Advisors](https://www.metatrader5.com/en/terminal/help/algotrading/trade_robots_indicators)
- [MQL5 Code Base](https://www.mql5.com/en/code/mt5)
- [TradeStation Strategy Automation](https://help.tradestation.com/10_00/eng/tradestationhelp/st_automation/strategy_automation.htm)
- [TradeStation Automated Strategies](https://kjtradingsystems.com/tradestation.html)
- [AI Agent Dashboard Comparison 2026](https://thecrunch.io/ai-agent-dashboard/)
- [AI-Trader Autonomous Trading](https://github.com/HKUDS/AI-Trader)
- [Top AI Trading Tools 2026](https://www.pragmaticcoders.com/blog/top-ai-tools-for-traders)
- [Tickeron AI Trading Platforms](https://tickeron.com/trading-investing-101/top-ai-trading-platforms-transforming-modern-markets/)
- [Best AI Trading Platforms 2026](https://liquidityfinder.com/insight/technology/best-ai-platforms-for-trading-and-analytics)

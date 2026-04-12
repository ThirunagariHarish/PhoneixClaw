# Phoenix Dashboard Redesign — Feature Proposals

**Date:** 2026-04-11
**Author:** Nova (Product Manager)
**Status:** Draft — Pending user validation

---

## Current State Summary

Phoenix already has a substantial dashboard with 30+ routes organized into four navigation sections (Agents, Trading, Analytics, System). Notable existing capabilities:

- **Market Command Center** — draggable/resizable widget grid with 50+ market widgets (TradingView embeds, heatmaps, screeners, options flow, breadth, etc.)
- **Agent Dashboard** — per-agent mission control with Portfolio, Trades, Chat, Intelligence, Logs, Rules tabs
- **Performance page** — PnL, win rate, Sharpe, drawdown with time-range selectors and multi-tab breakdowns
- **Positions & Trades** — data tables with filters, agent leaderboard, side panels
- **Risk & Compliance** — circuit breaker state, sector exposure, hedging status
- **Backtests** — 9-step pipeline visualization with live progress
- **Specialty pages** — Morning Briefing, AutoResearch, Prediction Markets, Brain Wiki, Macro-Pulse, 0DTE SPX, Narrative Sentiment, On-Chain Flow
- **Chat widget** — floating assistant for trade signals and conversation
- **Tremor chart library** — AreaChart, BarChart, LineChart, DonutChart, SparkChart, BarList, Tracker

### What Phoenix does NOT have (gaps identified during recon):

1. No dedicated **Home / Overview dashboard** (default route redirects to /trades)
2. No **equity curve** on the main Performance page (component exists but only used in agent detail)
3. No **real-time notification/alert center** (no bell icon, no alert inbox, no push notifications)
4. No **watchlist** functionality
5. No **trade journal / annotation** system
6. No **P&L calendar heatmap** (daily P&L on a calendar grid)
7. No **multi-chart layout** (TradingView-style side-by-side charts with synced symbols)
8. No **mobile-responsive** optimization (no evidence of responsive breakpoints beyond basic sm: classes)
9. No **onboarding / guided tour** for new users
10. No **keyboard shortcuts** global system (widget exists but no global hotkey layer)
11. No **portfolio allocation visualization** (pie/donut of holdings by sector, asset class)
12. No **agent comparison** view (side-by-side agent performance)
13. No **dark/light mode** toggle persistence indication or system-preference detection beyond basic ThemeContext

---

## Feature Proposals

### Category 1: Must-Have (Gaps vs. Modern Standards)

Every modern trading dashboard (TradingView, Thinkorswim, Robinhood, Wealthfront) includes these. Their absence makes Phoenix feel incomplete.

---

#### F01: Home Overview Dashboard
**One-line:** A single-screen command center showing portfolio value, today's P&L, active agents, recent trades, and top alerts.
**Page:** New `/` route (replaces redirect to /trades)
**Complexity:** M
**Priority:** P0
**Why:** Every trading platform opens to a summary view. Users should grasp their portfolio state in under 5 seconds ([Dashboard UX best practice](https://www.designrush.com/agency/ui-ux-design/dashboard/trends/dashboard-ux)). Currently Phoenix dumps users into the Trades table with no context.
**Key elements:**
- Portfolio value with % change (1D, 1W, 1M sparklines)
- Today's realized + unrealized P&L
- Active agents count + status badges
- Mini equity curve (last 30 days)
- Top 3 recent trades
- Active alerts / warnings
- Market status indicator (pre-market, open, after-hours, closed)

---

#### F02: Notification & Alert Center
**One-line:** A bell icon in the top bar with a dropdown inbox for trade fills, risk warnings, agent state changes, and signal arrivals.
**Page:** AppShell header (global)
**Complexity:** M
**Priority:** P0
**Why:** Real-time alerts are essential for investment apps to keep users informed of critical events without constant monitoring ([OneSignal](https://onesignal.com/blog/why-real-time-alerts-are-essential-for-investment-apps/)). Phoenix has agents generating events but no user-facing notification layer.
**Key elements:**
- Unread count badge on bell icon
- Categories: Trade fills, Risk alerts, Agent events, Signal arrivals
- Priority-based visual hierarchy (P0 = red, P1 = amber, P2 = blue)
- Mark as read / dismiss / act (navigate to relevant page)
- WebSocket-driven real-time push (infrastructure already exists via `useRealtimeQuery`)
- Optional browser push notifications

---

#### F03: Equity Curve on Performance Page
**One-line:** Interactive time-series chart of portfolio equity with drawdown overlay, benchmark comparison (SPY), and time-range selector.
**Page:** `/performance`
**Complexity:** S
**Priority:** P0
**Why:** The equity curve is the single most important chart for any trader evaluating performance. The `EquityCurveChart` component already exists and is used in agent detail, but the main Performance page only shows metric cards and tables — no chart.
**Reference:** TradingView's portfolio tracker, Robinhood's main portfolio view, every serious trading journal.

---

#### F04: P&L Calendar Heatmap
**One-line:** A monthly calendar grid where each day is color-coded by daily P&L (green gradient for gains, red gradient for losses).
**Page:** `/performance` (new tab)
**Complexity:** S
**Priority:** P0
**Why:** This is a standard feature in every trading journal (TraderSync, Tradervue, Kinfo). It gives instant visual feedback on consistency and streaks. No existing component covers this.
**Reference:** TraderSync daily P&L calendar, Tradervue calendar view.

---

#### F05: Watchlist
**One-line:** A persistent sidebar or page where users can save symbols, see live prices, sparklines, and one-click navigate to charts or place trades.
**Page:** New `/watchlist` route + optional sidebar panel
**Complexity:** M
**Priority:** P1
**Why:** TradingView, Thinkorswim, and Bloomberg all center around watchlists as the primary navigation metaphor for symbols ([TradingView watchlist features](https://www.tradingview.com/support/solutions/43000629990-leveraging-multi-chart-layouts-in-your-analysis/)). Phoenix has a TickerSearch widget but no persistent watchlist.
**Key elements:**
- Multiple named lists (e.g., "Mag7", "Earnings This Week", "Agent Positions")
- Live price, change %, volume, sparkline per symbol
- Sortable columns
- Right-click context menu: View chart, See agent trades for this symbol, Add alert

---

#### F06: Mobile-Responsive Layout
**One-line:** Responsive breakpoints and touch-friendly interactions so the dashboard is usable on tablets and phones.
**Page:** Global (AppShell + all pages)
**Complexity:** L
**Priority:** P1
**Why:** Portfolio managers need mobile access for real-time decision-making ([Indataipm](https://www.indataipm.com/customizable-dashboards-enhancing-user-experience-in-portfolio-management/)). The current layout has a collapsible sidebar and some `sm:` Tailwind classes, but no systematic mobile optimization. The Market Command Center's drag-grid would need a stacked mobile layout.
**Reference:** Robinhood mobile, Wealthfront mobile, TradingView mobile app.

---

### Category 2: High-Value (Differentiated AI Agent Features)

These features leverage Phoenix's unique AI agent architecture. No generic trading dashboard has them — they are competitive differentiators.

---

#### F07: Agent Decision Trail Visualizer
**One-line:** A visual pipeline diagram showing each step an agent took for a trade decision — signal parse, enrichment, ML inference, risk check, execution — with expandable details at each node.
**Page:** `/agents/:id` (new sub-tab or enhancement to existing Trades tab)
**Complexity:** M
**Priority:** P0
**Why:** Phoenix already captures `decision_trail` data per trade (the type exists in AgentDashboard.tsx). Visualizing this as an interactive flow diagram (not just JSON) makes the AI's reasoning transparent and builds user trust. This is a unique differentiator — no competitor shows agent reasoning pipelines visually.
**Key elements:**
- Horizontal step-flow (Signal -> Parse -> Enrich -> Inference -> Risk -> Execute)
- Each node: green check / red X / yellow warning icon + expandable card
- Confidence scores, feature counts, model predictions at each step
- "Why did the agent skip/reject this?" explanation surfaced prominently

---

#### F08: Agent Comparison Matrix
**One-line:** Side-by-side comparison of 2-4 agents across key metrics (P&L, win rate, Sharpe, drawdown, trade count) with overlaid equity curves.
**Page:** `/agents` (new comparison mode) or `/performance` tab
**Complexity:** M
**Priority:** P1
**Why:** Users running multiple agents (from different Discord channels or strategies) need to compare performance to allocate capital. The agent leaderboard table exists but lacks visual comparison. Bloomberg and institutional tools always support multi-asset/multi-strategy comparison.
**Key elements:**
- Checkbox selection on agent list to add to comparison
- Side-by-side metric cards
- Overlaid equity curves on single chart
- Win rate over time (rolling 20-trade)
- Best/worst trade comparison

---

#### F09: Agent Reasoning Chat (Conversational AI)
**One-line:** Upgrade the chat widget from basic message history to a full conversational AI interface where users can ask "Why did you buy TSLA?" or "What's your confidence on AAPL?" and get agent-aware answers.
**Page:** Global ChatWidget + `/agents/:id` Chat tab
**Complexity:** L
**Priority:** P1
**Why:** AI-powered dashboards in 2026 are moving toward conversational UI for data queries ([Dashboard design trends](https://fuselabcreative.com/top-dashboard-design-trends-2025/)). Phoenix already has chat infrastructure and Claude SDK agents. The chat currently just relays messages; it should understand context (positions, agent state, recent trades) and answer naturally.
**Key elements:**
- Natural language queries: "Show me my worst trades this week", "Why is Agent Alpha in WARNING state?"
- Context-aware responses pulling from positions, trades, agent logs
- Quick-action buttons in responses: "Close position", "Pause agent", "Show chart"
- Streaming responses with thinking indicator (agent already has thinking indicator support)

---

#### F10: Agent Activity Timeline
**One-line:** A chronological feed of all agent actions across the platform — signals received, trades executed, rules changed, errors encountered — filterable by agent, event type, and time.
**Page:** New `/activity` route or enhancement to `/logs`
**Complexity:** M
**Priority:** P1
**Why:** With multiple AI agents operating autonomously, users need a unified "what happened" view. The Logs page exists but is a raw log viewer. An activity timeline is a higher-level, user-friendly narrative of agent behavior.
**Key elements:**
- Timeline cards with icons per event type (trade, signal, error, rule change, agent start/stop)
- Agent avatar + name per event
- Expandable detail for each event
- Filter by agent, event type, time range
- Real-time streaming via WebSocket

---

#### F11: Live Agent Health Dashboard
**One-line:** A grid of agent cards showing real-time health status — heartbeat, last action, error rate, memory usage, current position count — with traffic-light indicators.
**Page:** `/agents` (enhanced list view or toggle to grid view)
**Complexity:** S
**Priority:** P1
**Why:** When running autonomous agents, operational health monitoring is as important as performance metrics. This is inspired by Kubernetes dashboards and DevOps monitoring tools. Phoenix has `worker_status` data but does not surface health metrics prominently.
**Reference:** Kubernetes dashboard pod status, Datadog service map.

---

#### F12: Strategy Playground / What-If Simulator
**One-line:** An interactive panel where users can adjust agent parameters (confidence threshold, position size, stop-loss %) and see simulated impact on historical performance.
**Page:** `/agents/:id` or `/strategies`
**Complexity:** L
**Priority:** P2
**Why:** TradingView's paper trading and backtesting let users experiment without risk. Phoenix has a full backtesting pipeline but no interactive parameter exploration. A lightweight "slider-based" what-if tool would differentiate from the heavy batch-backtest flow.
**Reference:** QuantConnect parameter optimization, TradingView strategy tester.

---

### Category 3: Nice-to-Have (Polish & Delight)

These quality-of-life features make the dashboard feel professional, smooth, and lovable.

---

#### F13: Trade Journal with Annotations
**One-line:** A journal view where each trade has a notes field, tags (e.g., "earnings play", "momentum"), screenshots, and a lessons-learned section.
**Page:** New `/journal` route or enhancement to Trades side panel
**Complexity:** M
**Priority:** P1
**Why:** Every serious trader keeps a journal. TraderSync, Tradervue, and Edgewonk all center on this. Phoenix records trades but has no annotation layer. Adding this makes Phoenix a complete trading system rather than just a bot dashboard.
**Key elements:**
- Per-trade notes (markdown)
- Tags / categories
- Attach chart screenshots
- "What went right / wrong" prompts
- Filter/search by tag, outcome, date

---

#### F14: Global Keyboard Shortcuts
**One-line:** A hotkey system (Cmd+K for command palette, Cmd+/ for shortcuts help, number keys for quick navigation) accessible from anywhere.
**Page:** Global
**Complexity:** S
**Priority:** P2
**Why:** Power users expect keyboard navigation. A KeyboardShortcutsWidget exists for the market page, but there is no global command palette or hotkey system. Bloomberg Terminal is entirely keyboard-driven.
**Key elements:**
- Cmd+K command palette (search pages, agents, symbols, actions)
- Keyboard navigation between sidebar items
- Quick actions: pause agent, refresh data, toggle dark mode
**Reference:** Linear's Cmd+K, Raycast, Bloomberg Terminal keyboard shortcuts.

---

#### F15: Customizable Dashboard Layouts (Saved Presets)
**One-line:** Let users save and switch between named dashboard layouts for different trading sessions (e.g., "Pre-Market Scan", "Active Trading", "End of Day Review").
**Page:** Market Command Center + potentially other pages
**Complexity:** M
**Priority:** P2
**Why:** TradingView's layout save/restore is a core feature ([TradingView layouts guide](https://www.tradingview.com/support/solutions/43000746975-tradingview-layouts-a-quick-guide/)). Phoenix's Market page has drag-and-drop widgets but no named preset system. Users rebuilding their layout each session is friction.
**Key elements:**
- Save current layout as named preset
- Quick-switch between presets
- Default presets: "Day Trading", "Swing Analysis", "Risk Review"
- Import/export layout JSON

---

#### F16: Portfolio Allocation Donut Chart
**One-line:** A donut/sunburst chart showing portfolio breakdown by sector, asset class, or agent — with drill-down on click.
**Page:** `/performance` or Home Overview
**Complexity:** S
**Priority:** P2
**Why:** Wealthfront, Robinhood, and every robo-advisor show portfolio allocation visually. Phoenix has position data but no allocation visualization. The DonutChart Tremor component already exists.
**Reference:** Wealthfront portfolio view, Robinhood portfolio diversification screen.

---

#### F17: Multi-Chart Synchronized Layout
**One-line:** A TradingView-style multi-chart view where 2-4 charts display simultaneously with synchronized symbol, timeframe, or crosshair.
**Page:** `/market` or new `/charts` route
**Complexity:** M
**Priority:** P2
**Why:** TradingView's multi-chart layout supports 2-16 synchronized charts and is a premium feature traders pay for ([TradingView multi-chart](https://www.tradingview.com/support/solutions/43000629990-leveraging-multi-chart-layouts-in-your-analysis/)). Phoenix has TradingViewChartWidget and MiniChartWidget but no synchronized multi-chart view.

---

#### F18: Onboarding Tour & Empty States
**One-line:** A guided walkthrough for new users highlighting key pages, plus informative empty states with CTAs when pages have no data.
**Page:** Global (first login) + all pages
**Complexity:** S
**Priority:** P2
**Why:** The dashboard has 30+ routes which can overwhelm new users. Well-designed empty states reduce confusion and guide users toward first actions ([UXPin dashboard principles](https://www.uxpin.com/studio/blog/dashboard-design-principles/)). An EmptyState component exists but usage across pages is inconsistent.
**Reference:** Linear onboarding, Notion first-run experience.

---

#### F19: Sound Alerts for Critical Events
**One-line:** Optional audio notifications for trade fills, circuit breaker trips, and agent errors — configurable per event type.
**Page:** Settings + global event handler
**Complexity:** S
**Priority:** P2
**Why:** Active traders using TradingView and Thinkorswim rely on sound alerts when not looking at screens ([Stock Alarm](https://stockalarm.io/)). Useful when Phoenix agents are trading autonomously and the user is multitasking.

---

#### F20: Dark Mode Polish & Theme Variants
**One-line:** Refine dark mode with consistent contrast ratios, add a "terminal green" theme option, and ensure all charts/widgets respect the theme.
**Page:** Global
**Complexity:** S
**Priority:** P2
**Why:** Trading dashboards are used for extended hours. Bloomberg's dark terminal aesthetic is iconic. Phoenix has dark mode via ThemeContext but some widgets (TradingView embeds, third-party iframes) may not respect it consistently.

---

## Priority Summary

| Priority | Count | Features |
|----------|-------|----------|
| P0       | 4     | F01 Home Overview, F02 Notifications, F03 Equity Curve, F04 P&L Calendar, F07 Decision Trail |
| P1       | 7     | F05 Watchlist, F06 Mobile, F08 Agent Compare, F09 AI Chat, F10 Activity Timeline, F11 Agent Health, F13 Trade Journal |
| P2       | 8     | F12 Strategy Playground, F14 Keyboard Shortcuts, F15 Layout Presets, F16 Allocation Chart, F17 Multi-Chart, F18 Onboarding, F19 Sound Alerts, F20 Theme Polish |

## Suggested Roadmap

**Phase 1 (Weeks 1-3): Foundation**
- F01 Home Overview Dashboard
- F02 Notification Center
- F03 Equity Curve on Performance
- F04 P&L Calendar Heatmap

**Phase 2 (Weeks 4-6): AI Differentiation**
- F07 Agent Decision Trail Visualizer
- F08 Agent Comparison Matrix
- F11 Live Agent Health Dashboard
- F10 Agent Activity Timeline

**Phase 3 (Weeks 7-10): Trading Essentials**
- F05 Watchlist
- F13 Trade Journal
- F09 AI Chat Upgrade
- F06 Mobile Responsive (start)

**Phase 4 (Weeks 11+): Polish**
- F14 Keyboard Shortcuts
- F15 Layout Presets
- F16 Allocation Chart
- F17 Multi-Chart
- F18 Onboarding
- F19 Sound Alerts
- F20 Theme Polish
- F12 Strategy Playground

---

## Research Sources

- [Dashboard UX Best Practices 2025 — DesignRush](https://www.designrush.com/agency/ui-ux-design/dashboard/trends/dashboard-ux)
- [Dashboard Design Principles — UXPin](https://www.uxpin.com/studio/blog/dashboard-design-principles/)
- [Top Dashboard Design Trends 2025 — Fuselab Creative](https://fuselabcreative.com/top-dashboard-design-trends-2025/)
- [Dashboard Design Guide 2026 — CreateBytes](https://createbytes.com/insights/ultimate-guide-dashboard-design-best-practices)
- [Customizable Portfolio Dashboards — Indataipm](https://www.indataipm.com/customizable-dashboards-enhancing-user-experience-in-portfolio-management/)
- [TradingView Features](https://www.tradingview.com/features/)
- [TradingView Multi-Chart Layouts](https://www.tradingview.com/support/solutions/43000629990-leveraging-multi-chart-layouts-in-your-analysis/)
- [TradingView Layouts Guide](https://www.tradingview.com/support/solutions/43000746975-tradingview-layouts-a-quick-guide/)
- [Bloomberg vs TradingView 2026 — Pineify](https://pineify.app/resources/blog/bloomberg-terminal-vs-tradingview-2025-comparison-for-traders-analysts-and-teams)
- [Real-Time Alerts for Investment Apps — OneSignal](https://onesignal.com/blog/why-real-time-alerts-are-essential-for-investment-apps/)
- [Stock Alarm — Real-Time Alerts](https://stockalarm.io/)
- [Fintech Dashboard UX Case Study — Medium](https://medium.com/@uipranavmp/fintech-dashboard-a-ux-ui-case-study-d1a70fcbde38)
- [Fintech Dashboards Guide — DataBrain](https://www.usedatabrain.com/blog/fintech-dashboards)
- [Stock Market Dashboard Templates — TailAdmin](https://tailadmin.com/blog/stock-market-dashboard-templates)
- [AI Trading Dashboard — GitHub (sivakirlampalli)](https://github.com/sivakirlampalli/ai-trading-dashboard)
- [Dashboard That Works for Startups 2026 — UX Planet](https://uxplanet.org/dashboard-that-works-a-step-by-step-guide-for-startups-in-2025-1cec1bfe7f9c)
- [Dashboard Design Principles 2026 — DesignRush](https://www.designrush.com/agency/ui-ux-design/dashboard/trends/dashboard-design-principles)

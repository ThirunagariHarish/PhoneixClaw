# Phoenix v2 User Guide

This guide explains how to use the Phoenix v2 dashboard, create agents, manage strategies, monitor positions, and work with automations and tasks.

---

## Dashboard Overview

The Phoenix v2 dashboard provides 12 main tabs:

| Tab | Purpose |
|-----|---------|
| **Trades** | View executed trades, filters, and trade history |
| **Positions** | Monitor open positions, P&amp;L, and risk metrics |
| **Performance** | Portfolio performance, charts, and analytics |
| **Agents** | Manage OpenClaw trading, strategy, monitoring, and task agents |
| **Strategies** | Strategy agents, backtest results, and strategy configuration |
| **Connectors** | Broker and data source connectors (Alpaca, etc.) |
| **Skills** | Skill catalog and agent skill configuration |
| **Market** | Market data and market overview |
| **Admin** | User management, API keys, and system settings |
| **Network** | OpenClaw nodes, instances, and network topology |
| **Tasks** | Task board for automations and scheduled jobs |
| **Settings** | User preferences, theme, and account settings |

On mobile, the bottom navigation shows **Trades**, **Positions**, **Performance**, **Agents**, and a **More** sheet for the remaining tabs.

---

## Agent Creation Walkthrough (5-Step Wizard)

1. **Navigate to Agents** — Click **Agents** in the sidebar or bottom nav.

2. **Click New Agent** — Opens the Create Agent dialog.

3. **Step 1 — Name** — Enter a descriptive name (e.g. `SPY-Discord-Trader`).

4. **Step 2 — Type** — Select agent type:
   - **Trading Agent** — Executes trades from signals
   - **Strategy Agent** — Runs strategies and backtests
   - **Monitoring Agent** — Monitors positions and risk
   - **Task Agent** — Handles scheduled tasks and automations

5. **Step 3 — OpenClaw Instance** — Select the OpenClaw instance where the agent will run. Ensure at least one instance is registered in **Network**.

6. **Step 4 — Description** — Optional description of the agent’s role.

7. **Step 5 — Data Source** — Configure the data source (e.g. Discord, API) and any additional config. Click **Create Agent** to finish.

After creation, agents appear in the grid. Use **Pause** / **Resume** to control execution and **Delete** to remove.

---

## Strategy Setup and Backtesting

1. **Go to Strategies** — View strategy cards and backtest results.

2. **Create Strategy** — Use the 3-step wizard:
   - Name and type (Mean Reversion, Momentum, Breakout, etc.)
   - Parameters (symbols, timeframe, risk settings)
   - Confirm and run initial backtest

3. **Backtest** — Run backtests from the strategy detail panel. Results show P&amp;L, Sharpe ratio, and drawdown.

4. **Deploy** — Link a strategy to an agent and instance for live or paper trading.

---

## Position Monitoring and Risk Management

- **Positions** tab — View open positions, entry price, current P&amp;L, and unrealized gains/losses.
- **Risk limits** — Configure `MAX_POSITION_SIZE`, `MAX_DAILY_LOSS`, `MAX_TOTAL_CONTRACTS` in Settings or environment.
- **Trailing stops** — Enable `TRAILING_STOP_ENABLED` and set `TRAILING_STOP_OFFSET` for automated exits.
- **Profit target / stop loss** — Set `DEFAULT_PROFIT_TARGET` and `DEFAULT_STOP_LOSS` per strategy or globally.

---

## Using Automations and the Task Board

- **Tasks** tab — Task board for automations, scheduled jobs, and manual tasks.
- **Create tasks** — Add tasks with due dates, assignees, and status.
- **Automations** — Configure triggers (e.g. time-based, event-based) and actions (e.g. run backtest, send alert).
- **Approval mode** — Set `APPROVAL_MODE=manual` to require human approval before trade execution; `auto` executes immediately.

---

## Mobile App Installation (PWA)

Phoenix v2 supports installation as a Progressive Web App (PWA):

1. Open the dashboard in a supported browser (Chrome, Safari, Edge).
2. Use **Add to Home Screen** (mobile) or **Install** (desktop) from the browser menu.
3. The app runs in a standalone window with offline-capable caching where supported.

The dashboard is responsive; the bottom nav and **More** sheet provide touch-friendly access to all tabs on mobile.

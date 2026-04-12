# System Tabs Deep Audit -- Phoenix Trade Bot

**Date:** 2026-04-11
**Author:** Nova (Product Manager)
**Scope:** 8 SYSTEM tabs + Home Overview at cashflow4us.com

---

## Table of Contents

1. [Home Overview (/)](#1-home-overview)
2. [Notifications (/notifications)](#2-notifications)
3. [Connectors (/connectors)](#3-connectors)
4. [Tasks (/tasks)](#4-tasks)
5. [Logs (/logs)](#5-logs)
6. [Admin (/admin)](#6-admin)
7. [Settings (/settings)](#7-settings)
8. [Prediction Markets (/polymarket)](#8-prediction-markets)

---

## 1. Home Overview

**File:** `apps/dashboard/src/pages/Home.tsx` (579 lines)

### Current State

**Components:**
- `MiniEquityCurve` -- 30-day Recharts area chart with gradient fill, auto-refresh every 30s
- `ActivityFeed` -- merged trade + agent events, sorted descending, capped at 10 items
- `AgentStatusGrid` -- running/active agents with per-agent today P&L, click-to-navigate
- `RecentTradesTable` -- last 5 trades with side icon, symbol, P&L, relative time
- `QuickActions` -- 4 static buttons (Create Agent, View Positions, Run Backtest, Morning Briefing)
- `useAnimatedNumber` hook -- ease-out quad animation for metric transitions

**Top Metrics (4 cards):**
- Total P&L (all time)
- Today's P&L (with % subtitle)
- Open Positions
- Active Agents (with running/paused/error breakdown)

**API Endpoints:**
- `GET /api/v2/performance/summary?range=1M`
- `GET /api/v2/trades/stats`
- `GET /api/v2/agents`
- `GET /api/v2/trades?limit=5`
- `GET /api/v2/portfolio/equity-curve?days=30`

**Data Flow:** All queries use TanStack Query with 30s refetch. Silent error swallowing (catch returns defaults). No WebSocket -- polling only.

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No system health indicator | P1 | User has no idea if Redis/Postgres/broker are healthy |
| No market status banner | P1 | No indication of market hours (pre-market, open, closed, holiday) |
| Equity curve is 30d only | P2 | No range selector (1D, 1W, 1M, 3M, YTD, ALL) |
| No win rate / Sharpe display | P2 | Key trading metrics absent from overview |
| Activity feed merges poorly | P2 | Agent status items use `last_trade_at` as time -- often null, causing sort issues |
| Quick Actions are static | P2 | Not personalized -- should surface contextual actions based on state |
| No portfolio allocation view | P2 | No sector/ticker breakdown of current holdings |
| Polling only, no WebSocket | P2 | 30s lag for real-time trading dashboard |
| No mobile responsiveness issues flagged but 2-col at lg breakpoint squeezes | P3 | Layout could benefit from single-col mobile priority |
| TODO comment in code | P3 | Line 448: "TODO: replace with /api/v2/positions/summary when available" |

### Competitive Research

Best-in-class trading dashboards (TradingView, Alpaca Dashboard, eToro) feature: real-time WebSocket updates, portfolio heat maps, multi-timeframe equity curves, system health indicators, and market session countdowns. The 2026 trend emphasizes real-time data visualization as a must-have, letting users see what is happening now rather than relying solely on historical data ([TailAdmin](https://tailadmin.com/blog/stock-market-dashboard-templates), [DesignRush](https://www.designrush.com/agency/ui-ux-design/dashboard/trends/dashboard-design-principles)).

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| H1 | System Health Bar | Top bar showing Redis, Postgres, broker connection status with colored dots | S | P0 | `Home.tsx`, new API `GET /api/v2/system/health` |
| H2 | Market Session Banner | Shows current market state (pre-market 4am-9:30am, open, after-hours, closed, holiday) with countdown timer | S | P1 | `Home.tsx`, `shared/utils/market_calendar.py` |
| H3 | Equity Curve Range Selector | Add pill buttons for 1D/1W/1M/3M/YTD/ALL ranges | M | P1 | `Home.tsx`, backend equity-curve endpoint |
| H4 | Performance Summary Row | Win rate, avg P&L per trade, Sharpe ratio, max drawdown -- second row of MetricCards | S | P1 | `Home.tsx` |
| H5 | Portfolio Treemap | Interactive treemap showing position allocation by ticker/sector | M | P2 | `Home.tsx`, new component `PortfolioTreemap.tsx` |
| H6 | Contextual Quick Actions | Show different actions based on state (e.g., "Resume paused agent" if agents paused, "Review risk alert" if risk breach) | M | P2 | `Home.tsx` |
| H7 | WebSocket Live Updates | Replace polling with WS for equity, trades, agent status | L | P2 | `Home.tsx`, `ws-gateway` service |

---

## 2. Notifications

**File:** `apps/dashboard/src/pages/Notifications.tsx` (373 lines)

### Current State

**Components:**
- `NotificationCard` -- bordered card with left-color-strip by category, icon, title, body (line-clamp-2), metadata row (category badge, event type badge, agent ID, ticker)
- Filter pills for categories: All, Trades, Risk, Agents, System
- Read/Unread/All toggle (segmented control)
- Pagination (20 per page, numbered buttons, prev/next)
- "Mark all read" bulk action

**Categories:** trades, risk, agents, system
**Event Types:** TRADE_FILLED, TRADE_REJECTED, RISK_BREACH, AGENT_ERROR, AGENT_STATUS, BACKTEST_COMPLETE, SYSTEM

**Data Source:** `useNotifications()` context hook with `fetchPage()`, `markAsRead()`, `markAllRead()`. Server-side pagination via offset/limit.

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No notification preferences per category | P1 | Settings page has toggles but they are not wired (no API call on change) |
| No push / browser notifications | P1 | Critical for risk breaches -- user may not be on the page |
| No notification sound | P2 | Trading platforms use audio alerts for fills/risk |
| No deep linking | P2 | Clicking a TRADE_FILLED notification should navigate to the trade detail |
| No bulk delete | P2 | Can mark read but cannot clear old notifications |
| No date range filter | P2 | Cannot filter by "today" or "last 7 days" |
| No real-time push | P2 | Notifications only appear on page refresh / fetch interval |
| No severity/urgency indicator | P3 | All notifications look the same weight -- risk breaches should feel urgent |

### Competitive Research

SaaS notification best practices emphasize: actionable notifications that link to the relevant resource, urgency-based visual hierarchy, opt-in browser push for critical alerts, batch digests for low-priority items, and A/B testing notification timing ([Toptal](https://www.toptal.com/designers/ux/notification-design), [Userpilot](https://userpilot.com/blog/notification-ux/), [Smashing Magazine](https://www.smashingmagazine.com/2025/07/design-guidelines-better-notifications-ux/)).

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| N1 | Browser Push Notifications | Service Worker + Notification API for RISK_BREACH and AGENT_ERROR events | M | P0 | New `sw-notifications.ts`, `NotificationContext.tsx` |
| N2 | Deep-Link Navigation | Click notification to navigate to trade/agent/backtest detail page | S | P1 | `Notifications.tsx` |
| N3 | Urgency Visual Hierarchy | RISK_BREACH gets pulsing red border + bell icon animation, TRADE_FILLED gets subtle green | S | P1 | `Notifications.tsx` |
| N4 | Audio Alerts | Configurable sound for fills and risk events (toggleable in Settings) | S | P2 | `Notifications.tsx`, `Settings.tsx` |
| N5 | Date Range Filter | "Today", "7d", "30d", custom date picker | S | P2 | `Notifications.tsx` |
| N6 | Bulk Delete / Archive | Select multiple and delete or archive old notifications | M | P2 | `Notifications.tsx`, backend endpoint |
| N7 | Wire Settings Toggles | Connect notification preference switches in Settings to a real API that filters server-side | M | P1 | `Settings.tsx`, new API `PUT /api/v2/user/notification-prefs` |

---

## 3. Connectors

**File:** `apps/dashboard/src/pages/Connectors.tsx` (~900 lines)

### Current State

**Supported Platforms (15):**
- Data Sources: Discord, Reddit, Twitter/X, Unusual Whales, News API, Webhook, WhatsApp, Telegram
- Market Data: Yahoo Finance, Polygon.io, Alpha Vantage
- Brokers: Alpaca, Interactive Brokers, Tradier, Robinhood

**Key Features:**
- Multi-step wizard dialog for adding connectors (platform select -> credentials -> config)
- Discord has a 4-step flow: platform -> credentials -> server discovery -> channel selection
- Step indicator progress bar in wizard
- Platform cards grouped by category (Data Sources, Market Data, Brokers)
- Tag system with suggested tags (signals, news, trends, options-flow, market-data, social)
- Connector cards with StatusBadge, last connected time, error messages
- Context menu (DropdownMenu) per connector with edit/delete
- Bulk select and delete via ConfirmDialog

**API Endpoints:**
- `GET /api/v2/connectors`
- `POST /api/v2/connectors`
- `DELETE /api/v2/connectors/:id`
- `POST /api/v2/connectors/discover-servers` (Discord)
- `POST /api/v2/connectors/discover-channels` (Discord)

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No connection health monitoring | P1 | No periodic health check / latency display per connector |
| No edit flow for existing connectors | P1 | Connector cards have edit in dropdown but no edit wizard shown in code |
| No connection test button | P1 | User cannot verify a connector works after creation |
| No data throughput metrics | P2 | No indication of messages/signals received per connector |
| No OAuth flow for platforms that support it | P2 | Reddit and Twitter use raw tokens instead of OAuth redirect |
| Massive component -- 900+ lines | P2 | Technical debt: wizard state management is complex, each platform duplicates form state |
| No connector logs / event history | P2 | No per-connector activity feed showing last messages received |
| No reconnect button | P2 | If a connector errors, user must delete and recreate |
| No import/export connector config | P3 | No way to backup or share connector configurations |

### Competitive Research

Integration marketplace UX best practices emphasize: searchable/filterable connector catalogs, one-click OAuth flows, visual field mapping during setup, health dashboards per integration, and retry/reconnect controls ([Truto](https://truto.one/blog/what-is-an-integration-marketplace-2026-architecture-guide/), [Webstacks](https://www.webstacks.com/blog/integration-marketplace)).

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| C1 | Connection Health Dashboard | Per-connector health card showing uptime, latency, last message time, error count | M | P0 | `Connectors.tsx`, new API `GET /api/v2/connectors/:id/health` |
| C2 | Test Connection Button | "Test" action on each connector card that validates credentials and returns success/failure | S | P1 | `Connectors.tsx`, new API `POST /api/v2/connectors/:id/test` |
| C3 | Edit Connector Wizard | Reuse add wizard in edit mode, pre-populating fields from existing config | M | P1 | `Connectors.tsx` |
| C4 | Reconnect Action | One-click reconnect for errored connectors | S | P1 | `Connectors.tsx`, backend |
| C5 | Data Throughput Metrics | Show messages/hour, signals/day sparkline per connector | M | P2 | `Connectors.tsx`, new API |
| C6 | Per-Connector Event Log | Expandable panel showing last 50 messages received through this connector | M | P2 | New component, backend |
| C7 | OAuth Flows | Replace raw token input with OAuth redirect for Reddit, Twitter where supported | L | P2 | `Connectors.tsx`, backend OAuth handlers |
| C8 | Refactor: Extract Platform Forms | Break 900-line monolith into per-platform form components | M | P2 | New files under `pages/connectors/` |

---

## 4. Tasks

**File:** `apps/dashboard/src/pages/Tasks.tsx` (593 lines)

### Current State

**Components:**
- Full Kanban board with 4 columns: Backlog, In Progress, Under Review, Completed
- Drag-and-drop via `@dnd-kit/core` + `@dnd-kit/sortable`
- `SortableTaskCard` with priority color strip, priority badge, agent role pill, skills pills, delete button
- `DragOverlay` for visual feedback during drag
- `PrioritySummaryBar` showing count by priority (low/medium/high/critical)
- Create Task dialog with: title, AI-assisted description (AiAssistPopover), agent role select, priority select, expandable skills checklist (8 skills)
- Optimistic updates for move and delete mutations

**Priorities:** low, medium, high, critical (with color-coded strips and badges)
**Agent Roles:** 9 roles (day-trader, technical-analyst, risk-analyzer, etc.)
**Skills:** 8 skills (market_data, signal_parsing, order_execution, etc.)

**API Endpoints:**
- `GET /api/v2/tasks`
- `POST /api/v2/tasks`
- `PATCH /api/v2/tasks/:id/move`
- `DELETE /api/v2/tasks/:id`

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No task detail / edit view | P1 | Cannot edit a task after creation -- only move or delete |
| No due dates | P1 | Tasks have no deadline, so nothing can be flagged overdue |
| No WIP limits | P2 | Kanban best practice: limit in-progress items to prevent overload |
| No task assignment to specific agents (only roles) | P2 | Role is abstract -- cannot assign to a specific running agent instance |
| No subtasks or checklists | P2 | Complex tasks cannot be broken into steps |
| No task comments or activity log | P2 | No collaboration trail on individual tasks |
| No search or filter | P2 | Cannot search tasks by title, filter by role, or filter by priority |
| No list view alternative | P3 | Only Kanban view; some users prefer list/table view |
| Drag between columns only -- no reorder within column | P3 | Cards can move between columns but ordering within is not persisted |

### Competitive Research

Kanban best practices include: WIP limits per column, cycle time tracking, throughput metrics, swimlanes by assignee, due date highlighting with overdue indicators, search/filter capabilities, and both board and list view options ([Atlassian](https://www.atlassian.com/software/jira/features/kanban-boards), [Gmelius](https://gmelius.com/blog/kanban-board-strategy-guide), [TransFunnel](https://www.transfunnel.com/blog/kanban-board-features-for-project-management)).

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| T1 | Task Detail / Edit Dialog | Click a task card to open full detail with editable fields | M | P0 | `Tasks.tsx`, `PATCH /api/v2/tasks/:id` |
| T2 | Due Dates + Overdue Highlighting | Add due_date field, show red highlight when overdue, amber when approaching | S | P1 | `Tasks.tsx`, backend model |
| T3 | Search and Filter Bar | Text search + priority filter dropdown + role filter | S | P1 | `Tasks.tsx` |
| T4 | WIP Limits | Configurable max cards per column, visual warning when exceeded | S | P2 | `Tasks.tsx` |
| T5 | Assign to Specific Agent | Dropdown to assign task to a specific running agent instance | M | P2 | `Tasks.tsx`, API changes |
| T6 | Task Comments | Activity/comment thread on each task for collaboration notes | M | P2 | New component, backend |
| T7 | List View Toggle | Switch between Kanban board and flat list/table view | M | P2 | `Tasks.tsx` |
| T8 | Cycle Time Metrics | Show avg time from Backlog->Completed, throughput chart | M | P3 | `Tasks.tsx`, new API |

---

## 5. Logs

**File:** `apps/dashboard/src/pages/Logs.tsx` (187 lines)

### Current State

**Components:**
- Source tab pills: all, client, server, agent, backtest
- Level dropdown: ALL, DEBUG, INFO, WARN, ERROR
- Text search (client-side filter on message + service)
- Auto-refresh toggle (3s interval) with spinning icon
- Fixed-column grid table: Time, Source, Level, Service, Message
- Expandable row detail showing: agent_id, backtest_id, progress bar, JSON details
- Color-coded level badges (DEBUG=zinc, INFO=blue, WARN=yellow, ERROR=red)
- Entry count display

**API Endpoint:** `GET /api/v2/system-logs?source=X&level=X&limit=200`

**LogEntry fields:** id, source, level, service, agent_id, backtest_id, message, details (JSON), step, progress_pct, created_at

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| No log export (CSV/JSON) | P1 | Cannot export logs for external analysis or incident review |
| No date/time range picker | P1 | Can only view the latest 200 -- no historical browsing |
| Client-side search only | P1 | Search filters the already-fetched 200 logs, not querying server |
| No log level aggregation / chart | P2 | No visual showing error rate over time |
| No bookmark / pin important logs | P2 | Cannot mark critical log entries for later review |
| No tail-follow mode | P2 | Auto-scroll to bottom as new logs arrive (common in log viewers) |
| No regex search | P2 | Only simple substring matching |
| No multi-select for bulk copy | P3 | Cannot select multiple log lines to copy to clipboard |
| Fixed column widths may clip content | P3 | 140px for time, 70px for source/level -- can be tight |
| Max 200 entries, no pagination | P2 | No way to load more or paginate through older logs |

### Competitive Research

Professional log viewers (Datadog, SigNoz, New Relic, Logdy) feature: live tail with auto-scroll, log volume histograms, regex and structured query support, saved views/filters, drill-down from chart to raw logs, correlation with traces/metrics, and CSV/JSON export ([SigNoz](https://signoz.io/blog/logs-ui/), [OpenObserve](https://openobserve.ai/blog/best-log-visualization-tools/), [Logdy](https://logdy.dev/), [PatternFly](https://www.patternfly.org/extensions/log-viewer/design-guidelines/)).

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| L1 | Date/Time Range Picker | Select start/end datetime for log queries, sent to backend | M | P0 | `Logs.tsx`, backend query params |
| L2 | Server-Side Search | Move search to backend with full-text query, replace client-side filter | M | P1 | `Logs.tsx`, backend search endpoint |
| L3 | Log Export | Export button for current filtered view as CSV or JSON download | S | P1 | `Logs.tsx` |
| L4 | Error Rate Histogram | Small bar chart above the log table showing log volume by level over time | M | P1 | `Logs.tsx`, new API `GET /api/v2/system-logs/histogram` |
| L5 | Tail-Follow Mode | Auto-scroll to newest entry as logs stream in, toggle on/off | S | P2 | `Logs.tsx` |
| L6 | Infinite Scroll / Pagination | Load more logs on scroll-to-top (reverse chronological), replace 200-cap | M | P2 | `Logs.tsx`, backend cursor pagination |
| L7 | Saved Filters / Views | Save commonly used filter combinations (e.g., "Agent errors only") | M | P2 | `Logs.tsx`, localStorage or API |
| L8 | Regex Search | Toggle for regex mode in search input | S | P3 | `Logs.tsx`, backend |

---

## 6. Admin

**File:** `apps/dashboard/src/pages/Admin.tsx` (461 lines)

### Current State

**Tabs:** Users, API Key Vault, Audit Log, Invitations, Roles

**Users Tab:**
- DataTable with columns: Name, Email, Role (badge), Last Login, Actions (edit/delete)
- Add User dialog: email, password, name, role
- Edit User dialog: name, role, is_active toggle
- Delete User confirmation dialog
- Roles hardcoded: admin, manager, trader, viewer

**API Key Vault Tab:**
- FlexCard per key with show/hide toggle, rotate button
- Displays masked key and last-used timestamp

**Audit Log Tab:**
- DataTable with columns: Time, User, Action, Resource
- Maps `user_id` to display, `target_type` as resource

**Invitations Tab:**
- Generate invitation code button
- Table showing code, created_by, status (available/used/expired), created_at
- Copy code to clipboard dialog
- Delete available invitations

**Roles Tab:**
- Static cards for each role with "Manage permissions" text (not functional)

**API Endpoints:**
- `GET /api/v2/admin/users`, `POST`, `PUT /:id`, `DELETE /:id`
- `GET /api/v2/admin/api-keys`
- `GET /api/v2/admin/audit-log`
- `GET /api/v2/admin/invitations`, `POST`, `DELETE /:id`

**Metric Cards:** Users count, API Keys count, Roles count, Audit Events count

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Roles tab is non-functional | P0 | "Manage permissions" is placeholder text -- no RBAC editor |
| No role-based route guarding | P1 | Admin page should be hidden from non-admin users |
| API Key rotate button is non-functional | P1 | Rotate button has no onClick handler wired |
| No API key creation flow | P1 | Can view keys but cannot create new ones in UI |
| No audit log filtering | P2 | Cannot filter audit by user, action, or date range |
| No audit log pagination | P2 | All entries loaded at once, no server-side pagination |
| No API key scoping | P2 | Keys have no permission scoping (read-only, full-access, etc.) |
| No user search | P2 | No search bar to find users in list |
| No invitation expiry configuration | P3 | Cannot set custom expiry when generating invitation codes |
| No user activity summary | P3 | No quick view of user's recent actions |
| Known QA bug: admin redirect issue | P1 | Previously reported -- non-admin users may encounter redirect loop |

### Competitive Research

Admin panels in trading platforms (Alpaca, Coinbase Business) feature: granular RBAC editors with permission matrices, API key scoping by endpoint, audit log search with structured filters, user session management (force logout), and IP whitelisting for API keys.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| A1 | RBAC Permission Editor | Real permission matrix per role (view trades, execute trades, manage agents, admin access, etc.) | L | P0 | `Admin.tsx`, new backend RBAC system |
| A2 | Route Guard for Admin | Hide admin tab and protect routes for non-admin users | S | P0 | Router config, auth context |
| A3 | API Key CRUD | Create, rotate (wired), revoke, scope (read/write/admin) | M | P1 | `Admin.tsx`, backend endpoints |
| A4 | Audit Log Filters | Filter by user, action type, date range; server-side pagination | M | P1 | `Admin.tsx`, backend query params |
| A5 | User Search | Search/filter bar above user table | S | P2 | `Admin.tsx` |
| A6 | Force Logout / Session Management | Admin can invalidate a user's session | M | P2 | `Admin.tsx`, backend session mgmt |
| A7 | IP Whitelist for API Keys | Allow restricting API keys by IP range | M | P3 | `Admin.tsx`, backend |

---

## 7. Settings

**File:** `apps/dashboard/src/pages/Settings.tsx` (120 lines)

### Current State

**Tabs:** Profile, Theme, Notifications, API

**Profile Tab:**
- Name input, Email input, Timezone select (5 timezones)
- Save button (NOT wired -- no mutation, no API call)

**Theme Tab:**
- Dark mode toggle switch via `useTheme()` context

**Notifications Tab:**
- 3 toggles: Trade alerts (default on), Risk alerts (default on), Agent status (default off)
- Toggles are NOT wired to any API -- `defaultChecked` only, state lost on refresh

**API Tab:**
- API Base URL input (reads from VITE_API_URL env var)
- Save button (NOT wired)

**Data Source:** `GET /api/v2/user/profile` with fallback defaults

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Save buttons are NOT wired | P0 | Profile and API Save buttons do not call any API -- changes are lost |
| Notification toggles are NOT wired | P0 | defaultChecked means state is lost on page refresh, never persisted |
| Only 5 hardcoded timezones | P1 | Missing most of the world's timezones |
| No password change | P1 | Users cannot change their password |
| No two-factor auth setup | P1 | No 2FA enrollment flow |
| No session management | P2 | Cannot see active sessions or revoke them |
| No email verification | P2 | No flow for changing email with verification |
| No data export (GDPR) | P2 | No "download my data" option |
| No danger zone (delete account) | P3 | No self-service account deletion |
| Theme only has dark/light | P3 | No system preference auto-detect, no accent color options |
| API tab purpose is unclear | P3 | End users should not configure API base URL |

### Competitive Research

SaaS settings pages (Notion, Linear, Figma) feature: organized sections with clear save states, password change with current password verification, 2FA enrollment with QR code, session list with device info, email change with verification, timezone with full Intl list, and notification granularity per channel (email, push, in-app) per category ([Userpilot](https://userpilot.com/blog/saas-ux-design/), [SaaSUI.design](https://www.saasui.design/), [Index.dev](https://www.index.dev/blog/saas-design-principles-ui-ux)).

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| S1 | Wire Profile Save | Connect Save button to `PUT /api/v2/user/profile` with toast feedback | S | P0 | `Settings.tsx`, backend endpoint |
| S2 | Wire Notification Preferences | Persist toggles to `PUT /api/v2/user/notification-prefs`, load on mount | S | P0 | `Settings.tsx`, backend endpoint |
| S3 | Change Password | Current password + new password + confirm, with validation | M | P1 | `Settings.tsx`, `POST /api/v2/user/change-password` |
| S4 | Full Timezone List | Use Intl.supportedValuesOf('timeZone') for complete list with search | S | P1 | `Settings.tsx` |
| S5 | 2FA Enrollment | TOTP setup with QR code display, verification code input | M | P1 | `Settings.tsx`, backend TOTP |
| S6 | Notification Granularity | Per-category (trades, risk, agents, system) x per-channel (in-app, push, email) matrix | M | P2 | `Settings.tsx`, backend |
| S7 | Session Management | Show active sessions with device/IP, ability to revoke | M | P2 | `Settings.tsx`, backend |
| S8 | System Theme Auto-Detect | Add "System" option that follows OS preference | S | P3 | `Settings.tsx`, ThemeContext |
| S9 | Remove API Tab | API base URL should not be user-configurable; remove or move to developer/admin section | S | P3 | `Settings.tsx` |

---

## 8. Prediction Markets

**File:** `apps/dashboard/src/pages/polymarket/index.tsx` (1133 lines) + supporting files (`VenueSelectorPills.tsx`, `TopBetsPanel.tsx`, `ChatTab.tsx`, `LogsTab.tsx`)

### Current State

**Sub-Tabs (9):** Markets, Strategies, Orders, Positions, Promotion, Briefing, Risk, Chat, Logs

**Markets Tab:**
- Venue selector pills (multi-venue support)
- Top Bets panel
- Filters: category text input, min volume, tradeable-only checkbox (URL-shareable via query params)
- Force scan button
- Table: Question, Category, Volume, Liquidity, Expiry, F9 (resolution risk score, lazily fetched per market)

**Strategies Tab:**
- Grid of StrategyCards showing: archetype, mode (LIVE/PAPER), paused state, bankroll, caps, Kelly cap
- Pause/Resume/Promote actions
- Promote dialog with typed confirmation, max notional input, risk acknowledgment checkbox

**Orders Tab:** Table with Submitted, Mode, Side, Qty, Limit, Status, Fees, Slippage bps, F9 score

**Positions Tab:** Table with Opened, Mode, Qty, Avg Entry, Unrealized P&L, Realized P&L, Closed

**Promotion Tab:** Strategy selector, last gate evaluation (raw JSON), audit history timeline

**Briefing Tab:** 4 metric cards (Paper P&L, Live P&L, Movers count, F9 risks count), kill switch status, raw JSON dump

**Risk Tab:** Kill switch status, jurisdiction attestation status, strategy counts (total/live/paused)

**Kill Switch:** Top-right button with activate (reason input) and rearm (type REARM) confirmation dialogs
**Jurisdiction Banner:** Attestation flow with checkbox + optional text

**API Endpoints (14):**
- `GET /api/polymarket/markets`, `POST /api/polymarket/markets/scan`
- `GET /api/polymarket/markets/:id/resolution-risk`
- `GET /api/polymarket/strategies`, `POST /:id/pause`, `POST /:id/resume`, `POST /:id/promote`
- `GET /api/polymarket/orders`
- `GET /api/polymarket/positions`
- `GET /api/polymarket/strategies/:id/promotion_audit`
- `GET /api/polymarket/briefing/section`
- `GET /api/polymarket/kill-switch/status`, `POST /activate`, `POST /deactivate`
- `GET /api/polymarket/jurisdiction/current`, `POST /attest`

### Gap Analysis

| Gap | Severity | Notes |
|-----|----------|-------|
| Briefing tab dumps raw JSON | P1 | `JSON.stringify(data, null, 2)` at end of BriefingTab is debug output |
| No market detail view | P1 | Cannot click a market row to see outcomes, price history, order book |
| No P&L chart for prediction markets | P1 | Only single number in briefing -- no time series |
| Promotion gate evaluation is raw JSON | P2 | Should be a visual pass/fail checklist per gate |
| No position close / exit action | P2 | Positions table is read-only, no close button |
| No order cancel action | P2 | Orders table is read-only, no cancel for pending orders |
| No market watchlist | P2 | Cannot save/bookmark markets of interest |
| No Kalshi integration | P2 | Major competitor -- Kalshi has $8.5B monthly volume, CFTC regulated |
| Orders/Positions tables have no pagination | P2 | Both load all data at once (up to 200) |
| No historical performance attribution | P3 | Cannot see which strategy/archetype performs best |

### Competitive Research

The prediction market landscape has expanded significantly. Kalshi is the leading regulated competitor with CFTC approval and $8.5 billion monthly volume. Robinhood launched prediction markets in March 2025. Fanatics Markets entered December 2025. PredictIt received full DCM/DCO approval in September 2025 ([DeFi Rate](https://defirate.com/prediction-markets/apps/), [Laika Labs](https://laikalabs.ai/prediction-markets/top-polymarket-alternatives), [The Block](https://www.theblock.co/post/383733/prediction-markets-kalshi-polymarket-duopoly-2025), [Gambling Insider](https://www.gamblinginsider.com/in-depth/105281/top-prediction-markets)). Key differentiators in competitors: real-time price charts per outcome, order book visualization, portfolio analytics with performance attribution, and mobile-first market discovery.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---------|-------------|------------|----------|-------|
| P1 | Clean Up Briefing Tab | Replace raw JSON dump with structured cards: movers list, new high-volume, resolutions, F9 risks as individual sections | M | P0 | `polymarket/index.tsx` |
| P2 | Market Detail View | Click-through from markets table to detail page showing outcomes, price chart, order book, F9 details | L | P1 | New `polymarket/MarketDetail.tsx` |
| P3 | Visual Gate Checklist | Replace raw JSON gate evaluation with pass/fail icons per gate (calibration, soak time, jurisdiction, F9) | M | P1 | `polymarket/index.tsx` |
| P4 | Prediction P&L Chart | Time-series line chart of paper and live P&L | M | P1 | New component, backend endpoint |
| P5 | Order Cancel Action | Cancel button for pending/open orders | S | P1 | `polymarket/index.tsx`, backend |
| P6 | Position Close Action | Close button for open positions with confirmation | S | P1 | `polymarket/index.tsx`, backend |
| P7 | Market Watchlist | Star/bookmark markets, filter to watchlist | M | P2 | `polymarket/index.tsx`, backend |
| P8 | Kalshi Venue Integration | Add Kalshi as a venue alongside Polymarket and Robinhood | L | P2 | Backend + `VenueSelectorPills.tsx` |
| P9 | Performance Attribution | Dashboard showing P&L by strategy archetype, hit rate, avg edge | M | P2 | New component |
| P10 | Orders/Positions Pagination | Server-side cursor pagination for both tables | M | P2 | `polymarket/index.tsx`, backend |

---

## Cross-Cutting Concerns

| # | Issue | Tabs Affected | Priority | Proposal |
|---|-------|---------------|----------|----------|
| X1 | No global error boundary per tab | All | P1 | Wrap each page in ErrorBoundary with "retry" button |
| X2 | No empty state illustrations | All | P2 | Replace text-only empty states with SVG illustrations + CTA |
| X3 | No loading skeletons | Home, Admin, Tasks | P2 | Replace "Loading..." text with shimmer skeleton components |
| X4 | No keyboard shortcuts | All | P3 | Add Cmd+K command palette for power users |
| X5 | Inconsistent PageHeader usage | Logs, Polymarket use manual h1; others use PageHeader component | P3 | Standardize all pages to use PageHeader |
| X6 | No breadcrumb navigation | Polymarket detail pages | P3 | Add breadcrumbs for sub-navigation |

---

## Priority Summary

### P0 -- Must Fix (Broken / Non-Functional)
1. **S1** Settings: Wire profile Save button
2. **S2** Settings: Wire notification preference toggles
3. **A1** Admin: RBAC permission editor (Roles tab is placeholder)
4. **A2** Admin: Route guard for non-admin users
5. **P1** Polymarket: Clean up Briefing raw JSON dump

### P1 -- High Priority (Key Gaps)
6. **H1** Home: System health bar
7. **H2** Home: Market session banner
8. **H3** Home: Equity curve range selector
9. **H4** Home: Performance summary metrics
10. **N1** Notifications: Browser push for critical events
11. **N2** Notifications: Deep-link navigation
12. **N7** Notifications: Wire settings toggles to API
13. **C1** Connectors: Connection health dashboard
14. **C2** Connectors: Test connection button
15. **C3** Connectors: Edit connector wizard
16. **T1** Tasks: Task detail/edit dialog
17. **T2** Tasks: Due dates with overdue highlighting
18. **L1** Logs: Date/time range picker
19. **L2** Logs: Server-side search
20. **A3** Admin: API key CRUD (create, rotate wired, revoke)
21. **A4** Admin: Audit log filters + pagination
22. **S3** Settings: Change password flow
23. **S4** Settings: Full timezone list
24. **S5** Settings: 2FA enrollment
25. **P2** Polymarket: Market detail view
26. **P3** Polymarket: Visual gate checklist
27. **P5** Polymarket: Order cancel action
28. **P6** Polymarket: Position close action

### P2 -- Medium Priority (Enhancements)
29-50. Remaining items from each tab (see individual sections above)

---

## Research Sources

- [TailAdmin -- Stock Market Dashboard Templates](https://tailadmin.com/blog/stock-market-dashboard-templates)
- [DesignRush -- Dashboard Design Principles 2026](https://www.designrush.com/agency/ui-ux-design/dashboard/trends/dashboard-design-principles)
- [Toptal -- Notification Design Guide](https://www.toptal.com/designers/ux/notification-design)
- [Smashing Magazine -- Notifications UX](https://www.smashingmagazine.com/2025/07/design-guidelines-better-notifications-ux/)
- [Userpilot -- Notification UX](https://userpilot.com/blog/notification-ux/)
- [SigNoz -- Logs UI](https://signoz.io/blog/logs-ui/)
- [OpenObserve -- Log Visualization Tools 2026](https://openobserve.ai/blog/best-log-visualization-tools/)
- [Logdy -- Real-Time Log Viewers](https://logdy.dev/)
- [PatternFly -- Log Viewer Design Guidelines](https://www.patternfly.org/extensions/log-viewer/design-guidelines/)
- [Truto -- Integration Marketplace Architecture Guide 2026](https://truto.one/blog/what-is-an-integration-marketplace-2026-architecture-guide/)
- [Webstacks -- Integration Marketplace Examples](https://www.webstacks.com/blog/integration-marketplace)
- [Atlassian -- Jira Kanban Boards](https://www.atlassian.com/software/jira/features/kanban-boards)
- [Gmelius -- Kanban Board Strategy Guide](https://gmelius.com/blog/kanban-board-strategy-guide)
- [TransFunnel -- Kanban Board Features](https://www.transfunnel.com/blog/kanban-board-features-for-project-management)
- [Userpilot -- SaaS UX Design](https://userpilot.com/blog/saas-ux-design/)
- [SaaSUI.design -- SaaS UI Patterns](https://www.saasui.design/)
- [Index.dev -- SaaS Design Principles 2026](https://www.index.dev/blog/saas-design-principles-ui-ux)
- [DeFi Rate -- Prediction Market Apps 2026](https://defirate.com/prediction-markets/apps/)
- [Laika Labs -- Polymarket Alternatives](https://laikalabs.ai/prediction-markets/top-polymarket-alternatives)
- [The Block -- Prediction Markets 2025 Duopoly](https://www.theblock.co/post/383733/prediction-markets-kalshi-polymarket-duopoly-2025)
- [Gambling Insider -- Top Prediction Markets 2026](https://www.gamblinginsider.com/in-depth/105281/top-prediction-markets)

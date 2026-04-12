# Trading Section Tab Audit — Deep Analysis

**Date:** 2026-04-11
**Author:** Nova (PM)
**Scope:** 5 tabs under the TRADING navigation section

---

## Table of Contents

1. [Trades (/trades)](#1-trades-trades)
2. [Positions (/positions)](#2-positions-positions)
3. [Daily Signals (/daily-signals)](#3-daily-signals-daily-signals)
4. [0DTE SPX (/zero-dte)](#4-0dte-spx-zero-dte)
5. [Watchlist (/watchlist)](#5-watchlist-watchlist)

---

## 1. Trades (/trades)

**File:** `apps/dashboard/src/pages/Trades.tsx`
**API Route:** `apps/api/src/routes/trades.py`

### Current State

**Components:**
- PageHeader with "Trades" title and LayoutDashboard icon
- 4 MetricCards in a grid: Total Trades, Filled, Rejected, Pending (from `/api/v2/trades/stats`)
- Left sidebar (4/12 cols): AgentLeaderboardTable — shows ranked agents by P&L, win rate, Sharpe, trade count, status dot (from `/api/v2/performance/by-agent` — endpoint does not exist in routes, silently fails)
- Right main area (8/12 cols): DataTable of trades with columns: Symbol, Side, Qty, Type, Agent (truncated 8-char ID), Status, Fill Price, Time
- Filters: text input for symbol, Select dropdown for status (PENDING, RISK_CHECK, APPROVED, SUBMITTED, FILLED, REJECTED, FAILED)
- SidePanel on row click: shows Symbol, Side, Qty, Status, Fill Price, Agent (clickable link to /agents/:id), Source, and rejection reason if applicable
- Auto-refresh: trades every 5s, stats every 10s, leaderboard every 30s

**Data:**
- Trades come from `TradeIntent` table (order-level: side, qty, order_type, limit/stop prices, status pipeline)
- Stats are simple counts by status
- Leaderboard calls `/api/v2/performance/by-agent` which has NO backend route — always returns empty array

**API Endpoints:**
| Endpoint | Exists | Notes |
|---|---|---|
| `GET /api/v2/trades` | Yes | Filters by status, symbol, agent_id. Limit/offset pagination. |
| `GET /api/v2/trades/stats` | Yes | Returns total/filled/rejected/pending counts |
| `GET /api/v2/performance/by-agent` | **NO** | Leaderboard always empty. Critical missing endpoint. |
| `GET /api/v2/trades/{trade_id}` | Yes | Single trade detail |
| `GET /api/v2/trades/today` | Yes | Today's AgentTrade records — not used by frontend |
| `GET /api/v2/trades/portfolio-summary` | Yes | Rich per-agent breakdown — not used by frontend |

### Competitive Research

**TradingView (2026):** Portfolio tracking with real trades, performance analytics, up to 5,000 transactions. Tracks entry/exit with P&L visualization. Missing: structured journaling, tagging, performance analytics for manual trades. [Source](https://www.tradingview.com/portfolios/)

**Thinkorswim:** Position Statement with full Greeks display, P/L Open, P/L Day, P/L YTD, margin requirement, market value. Right-click to create closing orders, analyze trades, group by strategy. Beta weighting tool. Real-time P&L on every position. [Source](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Monitor/Activity-and-Positions/Position-Statement)

**Robinhood:** Basic transaction CSV export. No built-in analytics beyond simple portfolio return graph. Third-party tools fill the gap with P&L analysis, Greeks at entry, strategy detection. [Source](https://www.tradesviz.com/brokers/Robinhood)

**TradesViz / TraderSync (journal tools):** 100s of actionable metrics, auto-imported trades, tagging, notes, strategy attribution, calendar heatmap of daily P&L, risk metrics, drawdown analysis. [Source](https://www.tradesviz.com/)

**Gold standard features for a Trades tab:**
- P&L on every trade (dollar and percent)
- Trade duration / holding time
- Win/loss streak tracking
- Calendar heatmap view
- Trade tags and notes
- Export to CSV
- Execution quality metrics (slippage, fill time)
- Grouped by strategy/agent
- Equity curve chart

### Gap Analysis

**Bugs / Broken:**
1. **Leaderboard always empty** — `/api/v2/performance/by-agent` has no backend route. The `AgentLeaderboardTable` renders "No agents" permanently.
2. **No P&L displayed** — The trades table shows fill price but not P&L (dollar or percent). The `/api/v2/trades/today` and `/portfolio-summary` endpoints exist but are unused.
3. **Date display risk** — `new Date(row.created_at).toLocaleString()` will show "Invalid Date" if `created_at` is empty string (which the backend returns as `""` when `created_at` is None).
4. **No pagination UI** — Backend supports limit/offset, but frontend sends no offset parameter. Shows max 50 trades with no way to page forward.

**Missing vs competitors:**
- No P&L per trade (dollar amount, percentage)
- No trade duration / holding period
- No equity curve or cumulative P&L chart
- No calendar heatmap of daily performance
- No export to CSV
- No trade notes / tags / journal entries
- No execution quality metrics (slippage, latency from signal to fill)
- No grouping by agent/strategy with sub-totals
- No date range filter (only status + symbol filters exist)
- No sort capability on any column

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files to Modify |
|---|---------|-------------|------------|----------|----------------|
| T1 | Build performance/by-agent endpoint | Create the missing API route that returns agent leaderboard data (P&L, win rate, Sharpe, trades) | M | **P0** | `apps/api/src/routes/trades.py` or new `performance.py`, register in `main.py` |
| T2 | Add P&L columns to trades table | Show pnl_dollar, pnl_pct on each trade row using data from AgentTrade join | S | **P0** | `Trades.tsx`, `trades.py` (extend TradeResponse) |
| T3 | Date range filter | Add date picker to filter trades by date range | S | **P1** | `Trades.tsx` |
| T4 | Pagination controls | Add Next/Prev page buttons, total count display | S | **P1** | `Trades.tsx`, shared `DataTable` component |
| T5 | Column sorting | Click column headers to sort | S | **P1** | `Trades.tsx` or enhance `DataTable` |
| T6 | Equity curve chart | Line chart of cumulative P&L over time above the trades table | M | **P1** | `Trades.tsx`, new `EquityCurve` component, new API endpoint |
| T7 | CSV export button | Export filtered trades to CSV download | S | **P2** | `Trades.tsx` |
| T8 | Trade journal notes | Add notes/tags field per trade, editable from SidePanel | M | **P2** | `Trades.tsx`, `trades.py`, DB migration for notes column |
| T9 | Calendar heatmap | Show daily P&L as a GitHub-style calendar heatmap | M | **P2** | New component, new API endpoint for daily aggregates |
| T10 | Execution quality metrics | Show slippage (signal price vs fill price), fill latency | M | **P2** | `Trades.tsx` SidePanel, extend `TradeResponse` |

---

## 2. Positions (/positions)

**File:** `apps/dashboard/src/pages/Positions.tsx`
**API Route:** `apps/api/src/routes/positions.py`

### Current State

**Components:**
- PageHeader with TrendingUp icon
- 3 MetricCards: Open Positions count, Unrealized P&L (with trend arrow), Realized P&L (with trend arrow) — from `/api/v2/positions/summary`
- Tabs component: "Open" and "Closed" tabs with counts in labels
- Open positions table columns: Symbol, Side (long/short badge), Qty, Entry price, Current price, P&L (colored), Stop Loss, Opened date
- Closed positions table columns: Symbol, Side, Qty, Entry price, Exit price, P&L (colored), Exit Reason, Closed date
- WebSocket real-time updates via `useRealtimeQuery` on "positions" channel — invalidates queries on events
- Fallback polling: open positions every 30s, closed every 60s, summary every 30s

**API Endpoints:**
| Endpoint | Exists | Notes |
|---|---|---|
| `GET /api/v2/positions` | Yes | Filters by status, symbol, agent_id. Default: OPEN |
| `GET /api/v2/positions/closed` | Yes | Closed positions only |
| `GET /api/v2/positions/summary` | Yes | Aggregate: open count, unrealized PnL, realized PnL |
| `GET /api/v2/positions/{id}` | Yes | Single position detail |
| `POST /api/v2/positions/{id}/close` | Yes | Manual close with exit_price + reason |

**Backend has a manual close endpoint that the frontend does NOT expose.**

### Competitive Research

**Thinkorswim:** Real-time position management with Greeks (Delta, Gamma, Theta, Vega) per position, Beta Weighting across portfolio, right-click to create closing/rolling orders, grouping by underlying/strategy, DTE countdown for options, margin impact display. [Source](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Monitor/Activity-and-Positions)

**IBKR TWS:** 659 configurable watchlist/position columns, real-time P&L with mark-to-market, risk navigator for portfolio risk analysis, what-if scenarios, automatic grouping by asset class/sector/strategy.

**Webull:** Clean mobile-first position cards with real-time P&L, one-tap close, percentage of portfolio allocation per position, cost basis tracking. [Source](https://www.a1trading.com/webull-platform-review/)

**Gold standard features for Positions:**
- One-click close / partial close buttons
- Position sizing as % of portfolio
- Risk metrics per position (distance to stop in %, max loss)
- Greeks display for options positions
- Ability to modify stop-loss / take-profit from the UI
- Group positions by agent, sector, or strategy
- P&L % return (not just dollar)
- Duration / DTE display
- Allocation pie chart
- Total portfolio exposure / beta

### Gap Analysis

**Bugs / Incomplete:**
1. **No close button** — Backend has `POST /positions/{id}/close` but the UI has no way to trigger it. Users cannot manually close positions.
2. **No take-profit column** on open positions table — The data model has `take_profit` but it is not displayed.
3. **No P&L percentage** — Only dollar P&L shown, no percentage return.
4. **No position detail view** — No SidePanel or row-click interaction. Cannot drill into a position.
5. **Date display** — `new Date(row.opened_at).toLocaleString()` full format is verbose and inconsistent across browsers.
6. **No pagination** — Same issue as Trades; hardcoded limit of 50.

**Missing vs competitors:**
- No manual close / partial close from UI
- No stop-loss / take-profit editing
- No P&L percentage return
- No position duration (time held)
- No portfolio allocation chart (pie/donut)
- No risk metrics per position (R-multiple, max drawdown, distance to stop)
- No grouping by agent/strategy
- No exposure summary (total long/short exposure, net exposure)
- No sort capability on columns
- No search/filter controls
- No real-time price flash animation on updates

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files to Modify |
|---|---------|-------------|------------|----------|----------------|
| P1 | Close position button | Add "Close" button per open position row, confirmation dialog, calls existing POST endpoint | S | **P0** | `Positions.tsx` |
| P2 | Position detail SidePanel | Click row to open side panel with full details: entry/current/SL/TP, P&L $/%,  agent link, duration | S | **P0** | `Positions.tsx` |
| P3 | P&L percentage column | Add return % column: `(current - entry) / entry * 100` | S | **P0** | `Positions.tsx` |
| P4 | Edit stop-loss / take-profit | Inline or modal editing of SL/TP, new PATCH endpoint | M | **P1** | `Positions.tsx`, `positions.py` (new PATCH route), DB |
| P5 | Portfolio allocation donut chart | Visual breakdown by symbol, sector, or agent | M | **P1** | `Positions.tsx`, new chart component |
| P6 | Position grouping | Group by agent or strategy with subtotals | M | **P1** | `Positions.tsx` |
| P7 | Exposure summary cards | Add: Total Long Exposure, Total Short Exposure, Net Exposure, Max Risk | S | **P1** | `Positions.tsx`, `positions.py` (extend summary) |
| P8 | Column sorting + filter bar | Sort any column, filter by symbol/agent | S | **P1** | `Positions.tsx` |
| P9 | Partial close | Close a portion of a position (e.g., sell half) | M | **P2** | `Positions.tsx`, `positions.py` (new endpoint) |
| P10 | Price flash animation | Green/red flash when current_price updates via WebSocket | S | **P2** | `Positions.tsx`, CSS |

---

## 3. Daily Signals (/daily-signals)

**File:** `apps/dashboard/src/pages/DailySignals.tsx`
**API Route:** `apps/api/src/routes/daily_signals.py`

### Current State

**Components:**
- PageHeader with Zap icon, "3-agent pipeline: Research -> Technical -> Risk"
- 5 MetricCards: Total Signals Today, Win Rate (7d) — hardcoded to 0%, Avg R:R, Active Signals, Pipeline Health
- Pipeline visualization: 3 agent cards (Research Analyst, Technical Analyst, Risk Analyzer) with status badges, last run time, signal counts, connected by chevron arrows
- Instance Connection card: instance selector dropdown + "Deploy Pipeline" button + status dot
- Signals Feed: full table with columns: Time, Symbol, Direction (with icon), Confidence, Source, Entry, Stop, Target, R:R, Status
- SidePanel on signal click: Entry, Stop Loss, Take Profit, R:R, Research Note, Technical Reference, Risk Analysis
- Auto-refresh: signals every 30s

**Data Mapping:**
- Signals are actually `AgentTrade` records joined with `Agent.name`, mapped to signal format
- Backend computes R:R as a rough estimate (2% stop assumption) since actual stop_loss is not stored on AgentTrade
- `stop_loss` and `take_profit` in the SignalResponse are always None/exit_price respectively — misleading labels
- Win Rate (7d) is hardcoded to 0 on frontend (computed client-side but no historical data)
- "Deploy Pipeline" calls `/api/v2/daily-signals/pipeline/deploy` which has NO backend route

**API Endpoints:**
| Endpoint | Exists | Notes |
|---|---|---|
| `GET /api/v2/daily-signals` | Yes | Today's AgentTrade records as signals |
| `GET /api/v2/daily-signals/pipeline` | Yes | Active agents and their trade counts |
| `POST /api/v2/daily-signals/pipeline/deploy` | **NO** | Deploy button is non-functional |
| `GET /api/v2/daily-signals/{signal_id}` | Yes | Signal detail |

### Competitive Research

**Best signal platforms (2026):** Signals should include instrument + direction, exact entry level, defined stop loss, take-profit targets, timeframe, and setup explanation. Real-time push delivery (sub-second, not polling). Pre-trade and post-trade management. [Source](https://www.daytrading.com/trading-signals)

**NinjaTrader/Optimus Futures:** 50+ built-in indicators, volume analysis, TPO (time-price-opportunity), alert integration, automated execution from signals via SignalStack. [Source](https://tradersunion.com/interesting-articles/day-trading-what-is-day-trading/best-signal-providers/)

**Gold standard for signal dashboards:**
- Signal performance tracking (win rate, avg return, by source agent)
- Historical signal backtesting
- One-click trade from signal
- Signal alerts (push notification, sound)
- Confidence distribution visualization
- Signal-to-trade conversion tracking
- Time-series chart overlaying signals on price action
- Filter by confidence threshold, direction, symbol

### Gap Analysis

**Bugs / Broken:**
1. **Win Rate (7d) always shows 0%** — Computed client-side as `0` with no logic to calculate.
2. **Deploy Pipeline button non-functional** — No backend POST endpoint exists for `/pipeline/deploy`.
3. **Stop Loss always null** — Backend maps `stop_loss=None` because AgentTrade has no stop_loss field. Signals show $0.00 for stop.
4. **Take Profit is actually exit price** — Misleading: `take_profit=trade.exit_price` means closed trades show their actual exit as "target."
5. **R:R is a rough guess** — Calculated assuming 2% risk, not actual stop distance. Often inaccurate.
6. **Pipeline visualization is fragile** — Hardcodes 3 agent names (Research Analyst, Technical Analyst, Risk Analyzer) with icon mapping. If agents have different names, no icon appears.
7. **No date navigation** — Backend supports `target_date` param but frontend always shows today.

**Missing vs competitors:**
- No historical signal browsing (date picker)
- No signal performance analytics (hit rate by agent, by symbol, by confidence bucket)
- No one-click "Trade this signal" button
- No signal alerts / notifications
- No confidence visualization (histogram or gauge)
- No chart overlay showing signals on price action
- No signal-to-trade conversion tracking
- No backtest-a-signal feature
- No signal expiration/TTL tracking

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files to Modify |
|---|---------|-------------|------------|----------|----------------|
| DS1 | Fix Win Rate calculation | Compute from closed AgentTrades in last 7 days on backend, return in pipeline response | S | **P0** | `daily_signals.py`, `DailySignals.tsx` |
| DS2 | Fix stop_loss / take_profit data | Add stop_loss field to AgentTrade or compute from agent's actual risk params | M | **P0** | `daily_signals.py`, DB migration, agent tools |
| DS3 | Date navigation | Add date picker to browse historical signals using existing `target_date` param | S | **P0** | `DailySignals.tsx` |
| DS4 | Remove or implement Deploy button | Either build the deploy endpoint or remove the broken button | S | **P0** | `DailySignals.tsx` or `daily_signals.py` |
| DS5 | Signal performance dashboard | Win rate, avg return, Sharpe by agent — new analytics endpoint | M | **P1** | New `daily_signals.py` endpoint, new chart components |
| DS6 | One-click trade from signal | "Trade" button on signal row that pre-fills an order with entry/SL/TP | M | **P1** | `DailySignals.tsx`, new order creation flow |
| DS7 | Confidence histogram | Visual distribution of signal confidence scores | S | **P1** | `DailySignals.tsx`, chart component |
| DS8 | Signal alerts | Push notification / sound when new signal arrives (WebSocket) | M | **P2** | `DailySignals.tsx`, WebSocket integration |
| DS9 | Price chart with signal overlay | Mini chart per signal showing entry/SL/TP on price action | L | **P2** | New chart component, market data integration |
| DS10 | Signal-to-trade tracking | Link signals to actual trades, show conversion rate | M | **P2** | `daily_signals.py`, schema changes |

---

## 4. 0DTE SPX (/zero-dte)

**File:** `apps/dashboard/src/pages/ZeroDteSPX.tsx`
**API Route:** `apps/api/src/routes/zero_dte.py`

### Current State

**Components:**
- PageHeader with Activity icon, "0DTE SPX Command Center", live SPX price + change + countdown to market close
- 7 MetricCards: SPX Price, VIX, GEX Net, Dealer Gamma Zone, 0DTE Volume, Put/Call Ratio, MOC Imbalance
- 5-tab inner layout:
  - **Gamma Levels:** Educational explainer + positive/negative gamma legend + GEX table (Strike, GEX Value, Type, Distance) with color-coded rows
  - **MOC Imbalance:** Educational explainer + countdown to 3:50 PM ET + 4 MetricCards (Direction, Amount, Historical Avg, Predicted Impact) + Trade Signal badge
  - **Vanna & Charm:** Educational explainer + 2 MetricCards (Vanna Level, Charm Bid) + strikes table (Strike, Vanna, Charm)
  - **0DTE Volume:** Educational explainer + 4 MetricCards (Call Volume, Put Volume, C/P Ratio, Gamma Squeeze) + strike heatmap grid + largest trades list
  - **EOD Trade Plan:** Educational explainer + AI composite trade plan (Direction, Instrument, Strikes, Size, Entry, Stop, Target) + signal badges + Execute Plan button
- Agent Config sidebar: Instance selector, Deploy 0DTE Agent button, Trading Mode (Observe/Paper/Live), Max Risk slider (0.5%-3%), Auto-execute toggle

**Backend Data Sources:**
- All data comes from `UnusualWhalesClient` — real API integration
- GEX: real gamma exposure data by strike
- MOC: approximated from market tide (call vs put premium) — NOT actual NYSE MOC data
- Vanna/Charm: derived from option chain Greeks (delta * vega approximation)
- Volume: real options flow aggregated by strike
- Trade Plan: composite of GEX + tide + flow sentiment

**API Endpoints:**
| Endpoint | Exists | Notes |
|---|---|---|
| `GET /api/v2/zero-dte/gamma-levels` | Yes | Real GEX data from Unusual Whales |
| `GET /api/v2/zero-dte/moc-imbalance` | Yes | Proxy from market tide, NOT real MOC |
| `GET /api/v2/zero-dte/vanna-charm` | Yes | Derived from option chain Greeks |
| `GET /api/v2/zero-dte/volume` | Yes | Real options flow data |
| `GET /api/v2/zero-dte/trade-plan` | Yes | AI composite signal |
| `GET /api/v2/zero-dte/spx-price` | **NO** | Frontend polls for price but no route exists |
| `GET /api/v2/zero-dte/metrics` | **NO** | Frontend polls for VIX/GEX summary but no route exists |
| `POST /api/v2/zero-dte/agent/create` | **NO** | Deploy button non-functional |
| `POST /api/v2/zero-dte/execute` | **NO** | Execute Plan button non-functional |

### Competitive Research

**SpotGamma:** Industry-leading GEX platform. Live GEX heatmap with proprietary bought-vs-sold model, real-time 0DTE coverage, calculates across 4 nearest expirations. 0DTE drives >50% of SPX daily volume. [Source](https://spotgamma.com/gamma-exposure-gex/)

**TanukiTrade:** TradingView integration for 0DTE GEX analysis — Gamma Walls, HVL (Gamma Flip), Put Walls across 220+ symbols. Minute-by-minute GEX updates. Discord community with slash commands. [Source](https://tanukitrade.com/)

**Barchart.com:** Free S&P 500 GEX visualization with clean bar charts by strike, positive/negative gamma differentiation. [Source](https://www.barchart.com/stocks/quotes/$SPX/gamma-exposure)

**SPXGamma.com:** Dedicated SPX gamma dashboard with live GEX levels, zero-gamma flip, key support/resistance derived from options positioning. [Source](https://www.spxgamma.com/)

**Gold standard for 0DTE dashboard:**
- Real-time GEX bar chart (not just table) with price overlay
- Live-updating options flow tape
- Actual NYSE MOC imbalance data (not proxy)
- Greeks surface visualization
- Historical GEX comparison (today vs yesterday)
- P&L tracking for executed 0DTE trades
- Backtested strategy performance
- Alert when gamma flip is breached

### Gap Analysis

**Bugs / Broken:**
1. **SPX price always shows 0/dash** — `/api/v2/zero-dte/spx-price` has no backend route. The header SPX price display is non-functional.
2. **VIX and summary metrics always show dashes** — `/api/v2/zero-dte/metrics` has no backend route. All 7 top MetricCards pull from this missing endpoint.
3. **Deploy 0DTE Agent button non-functional** — No POST `/agent/create` endpoint.
4. **Execute Plan button non-functional** — No POST `/execute` endpoint.
5. **MOC data is a proxy** — Uses call/put premium ratio, NOT actual NYSE MOC imbalance. The educational text describes NYSE MOC but the data is something different.
6. **Trading mode and auto-execute are local state only** — Changing Observe/Paper/Live or toggling auto-execute has no backend persistence or effect.
7. **Frontend/backend field mismatch on gamma-levels** — Frontend expects `[{strike, gex, type, distance}]` array but backend returns `{ticker, total_gex, call_gex, put_gex, zero_gamma_level, gex_by_strike: {}, updated_at}` object. The gamma table is likely empty.
8. **Frontend/backend mismatch on MOC** — Frontend expects `{direction, amount, historicalAvg, predictedImpact, tradeSignal, releaseTime}` but backend returns `{direction, net_premium, call_premium, put_premium, put_call_ratio, releaseTime, source}`. MetricCards show wrong data.
9. **Frontend/backend mismatch on volume** — Frontend expects `volumeByStrike` as `[{strike, calls, puts}]` but backend returns `[{strike, call_volume, put_volume}]`. Key names differ.
10. **Frontend/backend mismatch on trade-plan** — Frontend expects `{direction, instrument, strikes, size, entry, stop, target, signals: string[]}` but backend returns `{direction, instrument, zero_gamma, signals: object[], signal_count, updated_at}`. Most fields render as undefined.

**Missing vs competitors:**
- No GEX bar chart visualization (only table, which is broken)
- No real-time options flow tape
- No actual NYSE MOC data feed
- No historical GEX comparison
- No trade P&L tracking for 0DTE trades executed
- No alerts for gamma flip breach or significant flow
- No Greeks surface / skew visualization
- No implied volatility term structure chart
- No options chain viewer

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files to Modify |
|---|---------|-------------|------------|----------|----------------|
| Z1 | Build spx-price and metrics endpoints | Create `/spx-price` and `/metrics` routes using Unusual Whales or market data API | M | **P0** | `zero_dte.py` |
| Z2 | Fix gamma-levels frontend/backend contract | Align response shape: transform `gex_by_strike` dict into array with strike/gex/type/distance | S | **P0** | `zero_dte.py` (transform response) or `ZeroDteSPX.tsx` |
| Z3 | Fix MOC response mapping | Align field names between backend response and frontend expectations | S | **P0** | `ZeroDteSPX.tsx` or `zero_dte.py` |
| Z4 | Fix volume field names | Rename `call_volume`/`put_volume` to `calls`/`puts` in response, or update frontend | S | **P0** | `zero_dte.py` or `ZeroDteSPX.tsx` |
| Z5 | Fix trade-plan response contract | Make backend return `strikes`, `size`, `entry`, `stop`, `target`, `signals` as string array | M | **P0** | `zero_dte.py` |
| Z6 | GEX bar chart | Replace or augment gamma table with a horizontal bar chart (Recharts) showing GEX by strike with price line | M | **P1** | `ZeroDteSPX.tsx`, new chart component |
| Z7 | Build agent create + execute endpoints | Wire up Deploy Agent and Execute Plan to real backend logic | L | **P1** | `zero_dte.py`, agent gateway integration |
| Z8 | Persist trading mode + risk settings | Save Observe/Paper/Live and max risk to backend (agent config or user prefs) | M | **P1** | `ZeroDteSPX.tsx`, new API endpoint |
| Z9 | Live options flow tape | Scrolling real-time feed of large 0DTE trades as they happen | M | **P1** | New component, WebSocket or polling |
| Z10 | IV term structure chart | Show implied volatility across expirations | M | **P2** | New component, new API endpoint |
| Z11 | Historical GEX comparison | Overlay today's GEX vs yesterday's for trend analysis | M | **P2** | `zero_dte.py` (caching), new chart |
| Z12 | Alert on gamma flip breach | Push notification when SPX crosses zero-gamma level | M | **P2** | WebSocket, alert system |

---

## 5. Watchlist (/watchlist)

**File:** `apps/dashboard/src/pages/Watchlist.tsx`

### Current State

**Components:**
- PageHeader with Eye icon + inline form (text input + "Add" button) to add tickers
- 4 MetricCards: Watching (count), Gainers, Losers, Refresh interval ("60s")
- Empty state: centered icon + "Your watchlist is empty" message
- Full table with sortable headers: Symbol (link to TradingView), 5D Trend (SVG sparkline), Last Price, Change $, Change %, Volume, Mkt Cap, 52W Range (visual bar), Actions (Bell alert disabled, Trash delete)
- Tickers stored in `localStorage` (not server-persisted)
- Quotes fetched from `/api/v2/watchlist/quotes?symbols=AAPL,TSLA,...`
- On API failure, returns placeholder data with all nulls (graceful degradation)
- Sort by any numeric column or symbol name
- Tooltips on action buttons
- Auto-refresh every 60s

**Nice Built-in Features:**
- Sparkline SVG component (mini 5-day trend line, color-coded)
- 52-week range bar with position indicator
- Smart large number formatting (T/B/M/K)
- Color-coded P&L

**API Endpoints:**
| Endpoint | Exists | Notes |
|---|---|---|
| `GET /api/v2/watchlist/quotes` | **NO** | No backend route found. Frontend silently falls back to null placeholders. |

### Competitive Research

**TradingView (2026):** Unlimited watchlists, real-time data, custom columns, color/sorting, cross-device sync, 150+ screener filters, global market coverage, integrated alerts. [Source](https://www.tradingview.com/)

**IBKR:** 659 configurable watchlist columns, built-in trading journal, real-time streaming quotes, options chain integration, news feed per symbol, fundamentals data. [Source](https://www.stockbrokers.com/compare/interactivebrokers-vs-webull)

**Webull:** Fast mobile-first watchlist, 35 columns, real-time quotes, one-tap trade from watchlist, integrated charts, news per symbol, analyst ratings. [Source](https://www.a1trading.com/webull-platform-review/)

**Gold standard for Watchlist:**
- Server-persisted lists (not just localStorage)
- Multiple named watchlists (e.g., "Tech", "Dividends", "0DTE Plays")
- Price alerts with push notification
- One-click trade from watchlist
- Inline mini-chart (candlestick, not just sparkline)
- News headlines per ticker
- Analyst consensus / ratings
- Earnings date column
- Options activity / unusual volume flag
- Drag-and-drop reorder
- Bulk add (paste comma-separated tickers)
- Import from broker account (show all held positions in watchlist)

### Gap Analysis

**Bugs / Broken:**
1. **No backend endpoint** — `/api/v2/watchlist/quotes` does not exist. Every quote field shows "--" because the frontend catches the 404 and returns null placeholders. The entire table is non-functional.
2. **Bell alert button is permanently disabled** — Tooltip says "Coming soon: price alerts" but there is no implementation path.
3. **localStorage only** — Watchlist tickers are lost when clearing browser data or switching devices. No server persistence.

**Missing vs competitors:**
- No working quote data at all (endpoint missing)
- No multiple watchlists
- No server persistence / cross-device sync
- No price alerts
- No one-click trade from watchlist
- No news per ticker
- No earnings date / analyst ratings
- No options activity / unusual volume indicators
- No fundamentals (P/E, EPS, dividend yield)
- No candlestick mini-chart
- No drag-and-drop reorder
- No bulk add
- No integration with portfolio (auto-add held positions)

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files to Modify |
|---|---------|-------------|------------|----------|----------------|
| W1 | Build watchlist/quotes endpoint | Create API route that fetches live quotes (from broker or market data provider) for given symbols | M | **P0** | New `watchlist.py` route, register in `main.py` |
| W2 | Server-side watchlist persistence | Store watchlists in DB per user, sync across devices | M | **P0** | New DB table, new CRUD API, update `Watchlist.tsx` |
| W3 | Multiple named watchlists | Support creating/renaming/deleting watchlist groups | M | **P1** | `Watchlist.tsx`, new API endpoints, DB schema |
| W4 | Price alerts | Set alert on price threshold, trigger notification via WebSocket / push | L | **P1** | New alert system, `Watchlist.tsx`, backend alert engine |
| W5 | Add fundamentals columns | P/E ratio, EPS, dividend yield, next earnings date | M | **P1** | `Watchlist.tsx`, extend quotes endpoint |
| W6 | One-click trade from watchlist | "Trade" button per row that opens order entry pre-filled | S | **P1** | `Watchlist.tsx` |
| W7 | News headlines per ticker | Show latest 2-3 headlines per symbol, expandable | M | **P2** | New news API integration, `Watchlist.tsx` |
| W8 | Bulk add tickers | Paste "AAPL, TSLA, NVDA" to add multiple at once | S | **P2** | `Watchlist.tsx` |
| W9 | Drag-and-drop reorder | Let users manually sort their watchlist order | S | **P2** | `Watchlist.tsx` (dnd library) |
| W10 | Unusual activity flag | Show icon when a ticker has unusual options volume or large blocks | M | **P2** | New data source, `Watchlist.tsx` |

---

## Cross-Tab Issues

### Systemic Problems

1. **Frontend/backend contract mismatches** — The 0DTE tab has at least 4 major field-name mismatches between what the frontend expects and what the backend returns. This pattern suggests the frontend was built speculatively before backends were finalized. A shared OpenAPI spec or TypeScript code generation would prevent this.

2. **Missing API endpoints pattern** — 7+ frontend features call endpoints that do not exist:
   - `/api/v2/performance/by-agent` (Trades leaderboard)
   - `/api/v2/daily-signals/pipeline/deploy` (Daily Signals deploy)
   - `/api/v2/zero-dte/spx-price` (0DTE price)
   - `/api/v2/zero-dte/metrics` (0DTE metrics)
   - `/api/v2/zero-dte/agent/create` (0DTE deploy)
   - `/api/v2/zero-dte/execute` (0DTE execute)
   - `/api/v2/watchlist/quotes` (Watchlist quotes)

3. **No pagination UI anywhere** — All 5 tabs have backends with limit/offset but no UI pagination controls.

4. **No column sorting on DataTable** — Watchlist built custom sorting; other tabs have none. Should be a shared DataTable feature.

5. **Inconsistent date formatting** — Trades uses `toLocaleString({month, day, hour, minute})`, Positions uses raw `toLocaleString()`, DailySignals has a safe `formatTime` helper. No shared date utility.

6. **Silent error swallowing** — Most queries catch errors and return empty arrays with no user feedback. Users see empty tables with no explanation of whether data is loading, the backend is down, or there simply is no data.

### Priority Summary

**P0 — Must fix (broken/misleading):**
- Z1-Z5: Fix all 0DTE data mismatches and missing endpoints (page is largely non-functional)
- T1: Build performance/by-agent endpoint (leaderboard always empty)
- W1: Build watchlist quotes endpoint (all data shows "--")
- DS1-DS4: Fix win rate, stop_loss data, add date nav, fix deploy button
- P1: Add close position button

**P1 — Should build (competitive gap):**
- T2-T6: P&L columns, date filter, pagination, sorting, equity curve
- P2-P8: Position detail panel, P&L %, edit SL/TP, allocation chart, grouping, exposure cards
- DS5-DS7: Signal analytics, one-click trade, confidence viz
- Z6-Z9: GEX chart, wire up agent/execute, persist settings, flow tape
- W2-W6: Server persistence, multiple lists, alerts, fundamentals, trade button

**P2 — Nice to have (differentiation):**
- T7-T10: CSV export, journal notes, calendar heatmap, execution quality
- P9-P10: Partial close, price flash
- DS8-DS10: Alerts, chart overlay, signal-to-trade tracking
- Z10-Z12: IV chart, historical GEX, gamma flip alerts
- W7-W10: News, bulk add, drag-and-drop, unusual activity

---

## Research Sources

- [TradingView Portfolios](https://www.tradingview.com/portfolios/)
- [TradingView Review 2026](https://www.theinvestorscentre.co.uk/reviews/tradingview-review/)
- [TradesViz Trading Journal](https://www.tradesviz.com/)
- [Best Trading Journal 2026](https://www.tradesviz.com/blog/best-trading-journal-2026-comparison/)
- [Thinkorswim Position Statement](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Monitor/Activity-and-Positions/Position-Statement)
- [Thinkorswim Activity and Positions](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Monitor/Activity-and-Positions)
- [Robinhood Trade Analytics (TradesViz)](https://www.tradesviz.com/brokers/Robinhood)
- [Best Trading Signals 2026](https://www.daytrading.com/trading-signals)
- [Best Day Trading Signal Providers 2026](https://tradersunion.com/interesting-articles/day-trading-what-is-day-trading/best-signal-providers/)
- [SpotGamma GEX](https://spotgamma.com/gamma-exposure-gex/)
- [Barchart SPX Gamma Exposure](https://www.barchart.com/stocks/quotes/$SPX/gamma-exposure)
- [TanukiTrade GEX for TradingView](https://tanukitrade.com/)
- [SPXGamma.com](https://www.spxgamma.com/)
- [IBKR vs Webull 2026](https://www.stockbrokers.com/compare/interactivebrokers-vs-webull)
- [Webull Platform Review 2026](https://www.a1trading.com/webull-platform-review/)
- [Best Free Stock Watchlist 2026](https://www.daytradingprofitcalculator.com/blog/best-free-stock-watchlist-websites.html)

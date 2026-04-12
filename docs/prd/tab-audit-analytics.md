# Analytics Section Deep Audit -- 6 Tabs

**Date:** 2026-04-11
**Author:** Nova (PM Agent)
**Scope:** Performance, P&L Calendar, On-Chain Flow, Macro-Pulse, Narrative Sentiment, Risk & Compliance

---

## Table of Contents

1. [Performance](#1-performance)
2. [P&L Calendar](#2-pl-calendar)
3. [On-Chain Flow](#3-on-chain-flow)
4. [Macro-Pulse](#4-macro-pulse)
5. [Narrative Sentiment](#5-narrative-sentiment)
6. [Risk & Compliance](#6-risk--compliance)

---

## 1. Performance

**Route:** `/performance`
**Frontend:** `apps/dashboard/src/pages/Performance.tsx`
**Backend:** `apps/api/src/routes/performance.py`

### Current State

**Frontend components:**
- PageHeader with time-range selector (1D, 1W, 1M, 3M, YTD, ALL)
- 4 MetricCards: Total P&L, Win Rate, Sharpe Ratio, Max Drawdown
- 6 sub-tabs: Portfolio, By Account, By Agent, By Source, By Instrument, Risk
- DataTable component for tabular rows (columns: Name, P&L, Win Rate, Sharpe, Max DD, Trades)

**Backend endpoints:**
- `GET /api/v2/performance/summary` -- aggregate stats (total_pnl, win_rate, profit_factor). Sharpe and max_drawdown return `null`.
- `GET /api/v2/performance/portfolio` -- equity curve with daily aggregation
- `GET /api/v2/performance/agents` -- per-agent P&L/win_rate (no Sharpe, no max_dd)
- `GET /api/v2/performance/instruments` -- per-ticker P&L/trade count only
- `GET /api/v2/performance/risk` -- VaR 95/99, max drawdown from trade-level P&L

**Critical issues:**
- All 6 sub-tabs render `EMPTY_PERF` (hardcoded empty array). None of the tabs actually call the backend endpoints that exist. The data tables are decorative shells.
- Sharpe Ratio returns `null` from backend -- no calculation implemented.
- Max Drawdown in summary also returns `null`.
- No equity curve chart anywhere despite backend providing equity_curve data.
- "By Account" and "By Source" tabs have no backend endpoints at all.
- Time range selector sends `range=1M` but backend expects `period=7d` format -- mismatch.

### Competitive Research

| Feature | TradingView | Koyfin | Bloomberg PORT | Phoenix Status |
|---|---|---|---|---|
| Equity curve chart | Yes | Yes | Yes | Backend exists, not rendered |
| Sharpe ratio | Strategy tester | Yes | Yes | Returns null |
| Max drawdown chart | Strategy tester | Yes | Yes | Returns null |
| Sortino ratio | No | Yes | Yes | Missing |
| Calmar ratio | No | Yes | Yes | Missing |
| Benchmark comparison (vs SPY) | Yes | Yes (scatter) | Yes | Missing |
| Per-ticker attribution | No | Yes | Yes | Endpoint exists, not wired |
| AI-generated commentary | No | No | Yes (PORT Enterprise 2025) | Missing |
| Intraday P&L monitoring | Yes | Yes | Yes | Missing |
| Time-weighted returns (TWR) | No | Yes | Yes | Missing |
| Profit factor | No | No | No | Backend has it, not shown |
| Win/loss distribution histogram | Yes | No | No | Missing |
| Trade duration analysis | Yes (strategy) | No | No | Missing |

Sources:
- [TradingView Features](https://www.tradingview.com/features/)
- [Koyfin Features](https://www.koyfin.com/features/)
- [Bloomberg PORT AI Commentary](https://www.bloomberg.com/company/press/bloomberg-advances-portfolio-analytics-with-launch-of-ai-portfolio-commentary-in-port-enterprise/)

### Gap Analysis

1. **Sub-tabs are empty shells.** The 6 tabs all render `EMPTY_PERF`. Backend endpoints for agents, instruments, portfolio exist but are never called.
2. **Sharpe/Max DD not computed.** Backend returns null for both. Need a proper calculation using daily returns.
3. **No charts at all.** No equity curve, no drawdown chart, no histogram. Pure table view.
4. **Time range format mismatch.** Frontend sends `1M`, backend expects `7d`.
5. **Missing "By Account" and "By Source" backends.** No route exists.
6. **No benchmark comparison.** Cannot compare against SPY/QQQ.
7. **Profit factor exists in backend but is not displayed on the frontend.**

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---|---|---|---|---|
| P1 | Wire sub-tabs to real data | Connect Portfolio/Agent/Instrument tabs to existing backend endpoints | S | P0 | `Performance.tsx` |
| P2 | Equity curve chart | Render line chart from `/performance/portfolio` equity_curve data | S | P0 | `Performance.tsx` |
| P3 | Compute Sharpe ratio | Calculate Sharpe from daily P&L returns in `/summary` | M | P0 | `performance.py` |
| P4 | Compute max drawdown | Calculate drawdown from cumulative P&L in `/summary` | S | P0 | `performance.py` |
| P5 | Fix time range format | Align frontend `1M`/`1W` to backend `30d`/`7d` or vice versa | S | P0 | `Performance.tsx` or `performance.py` |
| P6 | Win/loss distribution chart | Histogram of trade P&L values using Recharts | S | P1 | `Performance.tsx` |
| P7 | Benchmark comparison | Add SPY return overlay to equity curve | M | P1 | `performance.py`, `Performance.tsx` |
| P8 | Sortino & Calmar ratios | Extended risk-adjusted return metrics | S | P1 | `performance.py`, `Performance.tsx` |
| P9 | Trade duration analysis | Avg hold time, distribution by duration bucket | M | P2 | `performance.py`, `Performance.tsx` |
| P10 | AI performance commentary | Claude-generated summary of performance drivers | L | P2 | New service, `Performance.tsx` |
| P11 | Show profit factor | Display existing profit_factor from summary | S | P0 | `Performance.tsx` |

---

## 2. P&L Calendar

**Route:** `/pnl-calendar`
**Frontend:** `apps/dashboard/src/pages/PnlCalendar.tsx`
**Backend:** No dedicated endpoint. Uses `GET /api/v2/trades` with client-side aggregation.

### Current State

**Frontend components:**
- Month/Year toggle view
- Calendar heatmap grid with color-coded P&L cells (green/red intensity)
- 4 MetricCards: Total P&L, Best Day, Worst Day, Win Rate
- Day detail popover on click (lists trades)
- Daily P&L bar chart (Recharts)
- Streak indicator (win/loss streak with dots)
- Year view (GitHub contribution-graph style, mini-months)

**Data flow:**
- Fetches `GET /api/v2/trades?start={}&end={}&limit=1000` and aggregates by day client-side
- Falls back to `generateMockData()` when API returns no data (random mock)
- Year view **always** uses mock data (hardcoded `generateMockData` for all 12 months)

**Issues:**
- TODO in source code: "Replace mock data with real API call once GET /api/v2/performance/daily is available"
- Year view is always mock -- never fetches real data for the year
- Client-side aggregation of up to 1000 trades is inefficient
- No filtering by agent or account
- No cumulative P&L running total line
- No weekly/monthly summary rollup

### Competitive Research

| Feature | TradeZella | Tradervue | Phoenix Status |
|---|---|---|---|
| Calendar heatmap | Yes | Yes | Yes (well-built) |
| Day detail with trades | Yes | Yes | Yes |
| Filter by strategy/setup | Yes (playbooks) | Yes (tags) | Missing |
| Cumulative equity line | Yes | Yes | Missing |
| Weekly/monthly rollup stats | Yes | Yes | Missing |
| Running P&L during trade | Yes | No | Missing |
| Export to CSV/PDF | Yes | Yes | Missing |
| Compare months side-by-side | No | No | Missing |
| Tag/categorize days | No | Yes | Missing |

Sources:
- [TradeZella Review 2026](https://tradingjournal.com/review/tradezella)
- [Tradervue P&L Calendar](https://www.tradervue.com/pnl-calendar)

### Gap Analysis

1. **Year view is always mock.** `yearPnlMap` calls `generateMockData` unconditionally -- never fetches API data.
2. **No server-side daily aggregation.** Client fetches raw trades and aggregates -- will break with high trade volume.
3. **No filter by agent/account/ticker.** Cannot drill down.
4. **No cumulative P&L line.** Only daily bars exist.
5. **No export.** Cannot download calendar data as CSV or image.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---|---|---|---|---|
| C1 | Server-side daily P&L endpoint | `GET /api/v2/performance/daily?year=&month=` returning aggregated daily P&L | M | P0 | New route in `performance.py`, `PnlCalendar.tsx` |
| C2 | Fix year view to use real data | Fetch 12 months of daily data, replace mock generation | S | P0 | `PnlCalendar.tsx` |
| C3 | Agent/account filter | Dropdown to filter calendar by agent or account | M | P1 | `PnlCalendar.tsx`, `performance.py` |
| C4 | Cumulative P&L line overlay | Running total line on the daily bar chart | S | P1 | `PnlCalendar.tsx` |
| C5 | Weekly/monthly summary row | Show weekly totals below calendar, monthly rollup card | S | P1 | `PnlCalendar.tsx` |
| C6 | Export to CSV | Download button for calendar data | S | P2 | `PnlCalendar.tsx` |
| C7 | Day tagging/journaling | Allow notes on each trading day | M | P2 | New model + endpoint, `PnlCalendar.tsx` |

---

## 3. On-Chain Flow

**Route:** `/onchain-flow`
**Frontend:** `apps/dashboard/src/pages/OnChainFlow.tsx`
**Backend:** `apps/api/src/routes/onchain_flow.py`

### Current State

**Frontend components:**
- 4 MetricCards: Whale Alerts (24h), Unusual Flow Volume, Dark Pool Activity, Institutional Sentiment
- 5 sub-tabs: Mag 7, Meme Stocks, Sector Flow, Indices, Whale Alerts
- Agent config sidebar (Deploy Flow Monitor with ticker/premium/size filters)
- Whale alerts table with live 30s refresh

**Backend endpoints:**
- `GET /api/v2/onchain-flow/whale-alerts` -- live from Unusual Whales API (top 20 by premium)
- `GET /api/v2/onchain-flow/mag7` -- flow summary for AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA
- `GET /api/v2/onchain-flow/meme` -- flow summary for GME, AMC, BBBY, PLTR, SOFI, RIVN
- `GET /api/v2/onchain-flow/sectors` -- 11 sector ETFs flow via UW API
- `GET /api/v2/onchain-flow/indices` -- SPY/QQQ/IWM/DIA with GEX data from UW

**Issues:**
- Top metrics (Unusual Flow Volume, Dark Pool %, Institutional Sentiment) show hardcoded defaults (`$0`, `0%`, `NEUTRAL`). Only whale_alerts_24h is computed (array length).
- No dark pool data integration despite frontend types expecting it (`dark_pool_pct`)
- Backend fetches sequentially -- Mag7 makes 7 sequential API calls; sectors makes 11. Very slow.
- BBBY is in meme tickers but delisted (bankrupt 2023).
- No historical flow comparison (today vs 5-day avg).
- No charting -- everything is tables/cards.
- No real-time streaming -- uses polling.

### Competitive Research

| Feature | Unusual Whales | WhaleStream | Phoenix Status |
|---|---|---|---|
| Real-time flow scanner | Yes (streaming) | Yes | Polling (30s) |
| Dark pool prints table | Yes (full) | Yes | Type exists, no data |
| Options heatmap by strike/expiry | Yes | No | Missing |
| GEX visualization (chart) | Yes | Yes | Data fetched, shown as text only |
| Historical flow overlay | Yes (paid) | No | Missing |
| Sector heatmap (visual) | Yes | No | Text list only |
| Custom watchlist alerts | Yes | Yes | Config exists, no push alerts |
| Volume profile by ticker | Yes | No | Missing |
| Open interest changes | Yes | Yes | Missing |
| Net premium flow chart | Yes | No | Missing |

Sources:
- [Unusual Whales Dark Pool Flow](https://unusualwhales.com/dark-pool-flow)
- [Unusual Whales Features](https://unusualwhales.com/features)
- [Unusual Whales Review 2026](https://tradewink.com/learn/unusual-whales-review)

### Gap Analysis

1. **3 of 4 top metrics are hardcoded defaults.** Only whale_alerts count works.
2. **No dark pool data.** Frontend types expect `dark_pool_pct` but backend never provides it.
3. **Sequential API calls.** Mag7 (7 calls), Sectors (11 calls), Meme (6 calls) -- should be parallelized.
4. **No charts/visualizations.** GEX data is fetched but rendered as plain text. No strike heatmap, no flow chart.
5. **Stale meme tickers.** BBBY is delisted.
6. **No open interest tracking.** Critical for options flow analysis.
7. **No net premium flow over time.** Cannot see intraday flow direction changes.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---|---|---|---|---|
| F1 | Fix top metrics | Compute real values for flow volume, dark pool %, sentiment from UW data | M | P0 | `onchain_flow.py`, `OnChainFlow.tsx` |
| F2 | Parallelize API calls | Use `asyncio.gather()` for Mag7/Sector/Meme fetches | S | P0 | `onchain_flow.py` |
| F3 | Remove BBBY, add current meme tickers | Update `MEME_TICKERS` list | S | P0 | `onchain_flow.py` |
| F4 | GEX visualization chart | Bar/area chart for GEX by strike price | M | P1 | `OnChainFlow.tsx`, possibly new UW endpoint |
| F5 | Net premium flow timeline | Intraday line chart of cumulative call vs put premium | M | P1 | `onchain_flow.py`, `OnChainFlow.tsx` |
| F6 | Dark pool integration | Fetch dark pool data from UW API, render in new sub-tab | M | P1 | `onchain_flow.py`, `OnChainFlow.tsx` |
| F7 | Open interest changes tab | Show OI change by strike for watched tickers | M | P1 | `onchain_flow.py`, `OnChainFlow.tsx` |
| F8 | Sector heatmap visualization | Treemap or grid heatmap instead of text list | M | P2 | `OnChainFlow.tsx` |
| F9 | WebSocket real-time streaming | Replace 30s polling with WS push for whale alerts | L | P2 | `ws-gateway`, `OnChainFlow.tsx` |
| F10 | Custom ticker watchlist | User-defined ticker list persisted to DB | M | P2 | New model, `onchain_flow.py`, `OnChainFlow.tsx` |

---

## 4. Macro-Pulse

**Route:** `/macro-pulse`
**Frontend:** `apps/dashboard/src/pages/MacroPulse.tsx`
**Backend:** `apps/api/src/routes/macro_pulse.py`

### Current State

**Frontend components:**
- Regime badge (RISK-ON/OFF/NEUTRAL/HAWKISH/DOVISH) with confidence %
- Agent config panel (create Macro-Pulse agent, refresh interval)
- 5 sub-tabs: Regime Overview, Fed Calendar, Economic Indicators, Geopolitical Risks, Trade Implications
- CPI line chart (Recharts) on Indicators tab
- MetricCards for economic indicators

**Backend endpoints:**
- `GET /api/v2/macro-pulse/regime` -- from `MacroDataFetcher` (yfinance + heuristics)
- `GET /api/v2/macro-pulse/calendar` -- static calendar of economic events
- `GET /api/v2/macro-pulse/indicators` -- live data: VIX, 10Y, DXY, gold, oil, SPY, QQQ, BTC
- `GET /api/v2/macro-pulse/geopolitical` -- **PLACEHOLDER**. Returns `{"status": "pending"}`.
- `GET /api/v2/macro-pulse/implications` -- **PLACEHOLDER**. Returns `{"status": "pending"}`.

**Critical issues:**
- Regime Overview sub-tab is entirely hardcoded. Cards show "Risk-On", "Hawkish Hold", "CPI 3.2% YoY", "3.7% unemployment" as static text, ignoring the API regime data.
- Geopolitical and Implications endpoints are stubs returning empty arrays with "pending" status.
- When API returns empty, page shows blank cards with no empty states.
- Only one chart (CPI). No VIX chart, no yield curve, no DXY trend.
- Economic indicators are flat MetricCards -- no sparklines or trend context.

### Competitive Research

| Feature | TradingView | Trading Economics | MacroMicro | Phoenix Status |
|---|---|---|---|---|
| Economic calendar with impact | Yes | Yes (300K indicators) | Yes | Partial (static list) |
| Live indicator charts | Yes | Yes | Yes | Only CPI |
| Yield curve visualization | No | Yes | Yes | Missing |
| Recession probability | No | Yes | Yes | Missing |
| Leading vs lagging indicators | No | Yes | Yes | Missing |
| Country comparison | No | Yes (196 countries) | Yes | Missing (US only) |
| Consensus vs actual | Yes | Yes | Yes | Missing |
| Calendar with alerts | Yes | Yes | Yes | No alerts |
| AI-generated macro analysis | No | No | No | Placeholder exists |
| Regime change history | No | No | No | Missing |

Sources:
- [TradingView Economic Calendar](https://www.tradingview.com/economic-calendar/)
- [Trading Economics Calendar](https://tradingeconomics.com/calendar)
- [FRED](https://fred.stlouisfed.org)

### Gap Analysis

1. **Regime Overview is fully hardcoded.** Static text ignoring live API data.
2. **2 of 5 sub-tabs are stubs.** Geopolitical and Implications return nothing.
3. **Single chart (CPI).** No VIX, yield curve, DXY, or commodity charts.
4. **No indicator sparklines.** MetricCards show point-in-time values with no trend context.
5. **No consensus vs actual.** Calendar shows dates but not forecasts or surprise direction.
6. **No alerts on high-impact events.** Calendar is passive.
7. **No FRED integration.** Despite `shared/data/fred_client.py` existing in the repo.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---|---|---|---|---|
| M1 | Wire Regime Overview to API | Replace hardcoded cards with live regime/indicators data | S | P0 | `MacroPulse.tsx` |
| M2 | Multi-indicator charts | VIX, 10Y, DXY sparkline/line charts using historical data | M | P0 | `macro_pulse.py`, `MacroPulse.tsx` |
| M3 | Implement geopolitical analysis | Use Claude to analyze top geopolitical risks from news feeds | L | P1 | `macro_pulse.py` |
| M4 | Implement trade implications | Claude-generated trade implications from macro data | L | P1 | `macro_pulse.py` |
| M5 | FRED data integration | Wire `shared/data/fred_client.py` for GDP, unemployment, CPI history | M | P1 | `macro_pulse.py`, `MacroPulse.tsx` |
| M6 | Yield curve visualization | 2s10s spread chart and full yield curve plot | M | P1 | `macro_pulse.py`, `MacroPulse.tsx` |
| M7 | Calendar consensus vs actual | Add forecast/actual/surprise to economic calendar events | M | P1 | `macro_pulse.py`, `MacroPulse.tsx` |
| M8 | Indicator sparklines | Add 30-day sparkline to each MetricCard | M | P2 | `MacroPulse.tsx`, `macro_pulse.py` |
| M9 | Regime change history timeline | Show historical regime transitions on a timeline | M | P2 | `macro_pulse.py`, `MacroPulse.tsx` |
| M10 | High-impact event alerts | Push notification when high-impact event is imminent | L | P2 | `macro_pulse.py`, notification service |

---

## 5. Narrative Sentiment

**Route:** `/narrative`
**Frontend:** `apps/dashboard/src/pages/NarrativeSentiment.tsx`
**Backend:** `apps/api/src/routes/narrative_sentiment.py`

### Current State

**Frontend components:**
- 4 MetricCards: Market Sentiment, Fear & Greed Index, Twitter Velocity, News Sentiment Avg
- Agent config panel (source toggles: twitter/news/reddit/sec, alert threshold slider)
- 5 sub-tabs: Sentiment Feed, Fed Watch, Social Pulse, Earnings Intelligence, Analyst Moves

**Backend endpoints:**
- `GET /api/v2/narrative/feed` -- FinBERT-scored Discord channel messages (last 24h). Real sentiment analysis.
- `GET /api/v2/narrative/fed-watch` -- Upcoming FOMC events from static calendar.
- `GET /api/v2/narrative/social` -- Ticker mention counts from Discord (not Twitter/Reddit).
- `GET /api/v2/narrative/earnings` -- From yfinance calendar data.
- `GET /api/v2/narrative/analyst-moves` -- From yfinance recommendations.

**Issues:**
- "Twitter Velocity" metric has no Twitter data source. Shows hardcoded fallback `0.78`.
- "Fear & Greed Index" shows hardcoded `62`. No CNN Fear & Greed integration.
- Source toggles (twitter/news/reddit/sec) are UI-only -- no backend filtering by source type.
- Social Pulse only has Discord data, not Twitter or Reddit despite UI suggesting otherwise.
- Sentiment heatmap data (`social.heatmap`) always returns empty array from backend.
- Feed items show `content` but frontend expects `headline` -- field name mismatch.
- No time-series sentiment chart (sentiment over time).
- Earnings data is basic (date + estimates). No historical beat/miss rate.

### Competitive Research

| Feature | Bloomberg | Unusual Whales | FinViz | Phoenix Status |
|---|---|---|---|---|
| Multi-source sentiment aggregation | Yes | Yes | Yes | Discord only |
| Fear & Greed gauge | No | No | No (CNN) | Hardcoded |
| Sentiment time-series chart | Yes | No | No | Missing |
| Earnings surprise tracking | Yes | Yes | Yes | Missing |
| Analyst rating changes with price target | Yes | Yes | Yes | Partial (no price target from yfinance) |
| SEC filing sentiment (10-K, 8-K) | Yes | No | No | Toggle exists, no data |
| Insider trading tracking | No | Yes | Yes | Missing |
| Sentiment alerts | No | Yes | No | Threshold slider UI only |
| WSB/Reddit integration | No | No | No | UI expects it, not implemented |
| Historical sentiment comparison | Yes | No | No | Missing |

Sources:
- [Bloomberg PORT Enterprise](https://www.bloomberg.com/professional/products/bloomberg-terminal/portfolio-analytics/)
- [Unusual Whales Features](https://unusualwhales.com/features)

### Gap Analysis

1. **Fear & Greed and Twitter Velocity are hardcoded.** No real data sources.
2. **Source toggles are non-functional.** UI has twitter/news/reddit/sec toggles but backend only has Discord.
3. **Social heatmap is always empty.** Backend returns `[]` for heatmap.
4. **No sentiment time-series.** Cannot see sentiment trends over time.
5. **Field name mismatch.** Feed expects `headline`, API returns `content`.
6. **No earnings beat/miss history.** Only shows next earnings date.
7. **Alert threshold slider does nothing.** No alerting mechanism.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---|---|---|---|---|
| N1 | Fix feed field mapping | Align frontend field names (`headline`/`source`/`score`) with API response | S | P0 | `NarrativeSentiment.tsx` |
| N2 | Build sentiment heatmap | Compute per-ticker sentiment scores and return in heatmap array | M | P0 | `narrative_sentiment.py` |
| N3 | Fear & Greed integration | Scrape CNN Fear & Greed Index or compute from VIX/breadth/momentum | M | P1 | `narrative_sentiment.py`, `NarrativeSentiment.tsx` |
| N4 | Sentiment time-series chart | Line chart of aggregate sentiment over 7/30 days | M | P1 | `narrative_sentiment.py`, `NarrativeSentiment.tsx` |
| N5 | Remove non-functional source toggles | Remove or implement Twitter/Reddit/SEC data sources | S or L | P1 | `NarrativeSentiment.tsx`, potentially new integrations |
| N6 | Earnings beat/miss history | Add historical EPS surprise data from yfinance | M | P1 | `narrative_sentiment.py`, `NarrativeSentiment.tsx` |
| N7 | Wire alert threshold | Trigger notification when sentiment crosses threshold | M | P2 | `narrative_sentiment.py`, notification service |
| N8 | Reddit/WSB integration | Scrape or API for Reddit sentiment data | L | P2 | New service, `narrative_sentiment.py` |
| N9 | Insider trading tracker | SEC Form 4 filing data | L | P2 | New service, `NarrativeSentiment.tsx` |

---

## 6. Risk & Compliance

**Route:** `/risk`
**Frontend:** `apps/dashboard/src/pages/RiskCompliance.tsx`
**Backend:** `apps/api/src/routes/risk_compliance.py`

### Current State

**Frontend components:**
- 4 MetricCards: Portfolio VaR, Daily P&L %, Margin Usage %, Circuit Breaker badge
- Agent config panel (max daily loss slider, max sector exposure slider)
- 5 sub-tabs: Circuit Breaker, Position Limits, Risk Checks, Compliance, Hedging

**Backend endpoints:**
- `GET /api/v2/risk/status` -- Daily P&L, open positions, consecutive losses, circuit breaker state. Real data from AgentTrade.
- `GET /api/v2/risk/position-limits` -- Ticker concentration from open positions. Real data.
- `GET /api/v2/risk/checks` -- Agent logs (WARNING/ERROR level). Real data.
- `GET /api/v2/risk/compliance` -- PDT rule check + wash sale detection. Real data.
- `GET /api/v2/risk/hedging` -- Protective puts from open positions. Real data.
- `POST /api/v2/risk/circuit-breaker/reset` -- Manual reset (returns static success).

**Issues:**
- VaR shows `$0` because `/status` does not return VaR (that is in `/performance/risk` endpoint, different route).
- Margin Usage % is always `0` -- no actual margin data from broker.
- Agent config sliders (max daily loss, max sector exposure) are UI-only. Values not sent to backend or persisted.
- Position Limits tab expects sector exposure data but backend only returns ticker concentration (no sector mapping).
- Risk Checks tab shows raw agent logs, not structured risk check results.
- Circuit breaker reset is a no-op (returns static JSON, no state change).
- No drawdown chart, no VaR confidence interval visualization.
- No real-time position P&L tracking.

### Competitive Research

| Feature | Bloomberg MARS | Interactive Brokers | Koyfin | Phoenix Status |
|---|---|---|---|---|
| Real-time VaR | Yes | Yes | No | Different endpoint, not wired |
| Margin monitoring | Yes | Yes | No | Shows 0% always |
| Stress testing | Yes | No | No | Missing |
| Correlation matrix | Yes | No | Yes | Missing |
| Greeks exposure (delta/gamma/vega) | Yes | Yes | No | Missing |
| PDT rule tracking | No | Yes | No | Implemented (real) |
| Wash sale detection | No | Yes | No | Implemented (real) |
| Real-time alerts on breaches | Yes | Yes | No | Missing |
| Position-level stop-loss tracking | No | Yes | No | Missing |
| Compliance audit log | Yes | No | No | Agent logs only |

Sources:
- [Bloomberg Portfolio Analytics](https://www.bloomberg.com/professional/products/bloomberg-terminal/portfolio-analytics/)
- [Koyfin Review 2026](https://financialmodelshub.com/koyfin-review-2026-pricing-pros-cons-features-alternatives-20-off-voucher/)

### Gap Analysis

1. **VaR not wired.** `/risk/status` does not return VaR; it exists in `/performance/risk` but frontend calls the wrong endpoint.
2. **Margin usage is always 0.** No broker margin data integration.
3. **Agent config sliders are decorative.** Values not persisted or sent anywhere.
4. **No sector exposure data.** Position limits endpoint has no sector mapping for tickers.
5. **Circuit breaker reset is a no-op.** No actual state management.
6. **No visualization.** All risk data is text/progress bars. No drawdown chart, no VaR distribution.
7. **No Greeks exposure.** Critical for options-heavy portfolio.
8. **No stress testing.** Cannot model "what if VIX doubles" scenarios.

### Implementation Proposals

| # | Feature | Description | Complexity | Priority | Files |
|---|---|---|---|---|---|
| R1 | Wire VaR from correct endpoint | Call `/performance/risk` for VaR or merge into `/risk/status` | S | P0 | `RiskCompliance.tsx` or `risk_compliance.py` |
| R2 | Sector mapping for positions | Map tickers to sectors (static or via yfinance) for sector exposure bars | M | P0 | `risk_compliance.py` |
| R3 | Persist risk config | Save max daily loss / sector exposure thresholds to DB, enforce in risk checks | M | P1 | `risk_compliance.py`, new model |
| R4 | Broker margin data | Fetch real margin usage from Robinhood/IBKR connector | M | P1 | `risk_compliance.py`, broker adapters |
| R5 | Implement circuit breaker state | Persist and enforce circuit breaker state across agents | M | P1 | `risk_compliance.py`, `circuit_breaker.py` |
| R6 | Drawdown chart | Visualize drawdown curve over time | M | P1 | `RiskCompliance.tsx`, `performance.py` |
| R7 | Correlation matrix | Heatmap of ticker correlation in current portfolio | M | P1 | `risk_compliance.py`, `RiskCompliance.tsx` |
| R8 | Greeks exposure dashboard | Delta, gamma, vega, theta exposure for options positions | L | P2 | `risk_compliance.py`, `RiskCompliance.tsx` |
| R9 | Stress testing scenarios | Predefined scenarios (VIX spike, rate hike, sector crash) | L | P2 | New service, `RiskCompliance.tsx` |
| R10 | Real-time risk alerts | WebSocket push when thresholds are breached | L | P2 | `ws-gateway`, notification service |

---

## Summary: Cross-Tab Priority Matrix

### P0 -- Must Fix (broken/empty/misleading)

| ID | Tab | Issue |
|---|---|---|
| P1-P5, P11 | Performance | Sub-tabs empty, Sharpe/MaxDD null, no charts, format mismatch |
| C1-C2 | P&L Calendar | Year view always mock, no server-side aggregation |
| F1-F3 | On-Chain Flow | 3/4 metrics hardcoded, sequential API calls, delisted ticker |
| M1 | Macro-Pulse | Regime overview hardcoded |
| N1-N2 | Narrative | Feed field mismatch, empty heatmap |
| R1-R2 | Risk | VaR not wired, no sector mapping |

### P1 -- High Value Additions

| ID | Tab | Feature |
|---|---|---|
| P6-P8 | Performance | Distribution chart, benchmark, Sortino/Calmar |
| C3-C5 | P&L Calendar | Agent filter, cumulative line, weekly summaries |
| F4-F7 | On-Chain Flow | GEX chart, premium flow, dark pool, OI changes |
| M2-M7 | Macro-Pulse | Multi-chart indicators, geopolitical AI, FRED, yield curve |
| N3-N6 | Narrative | Fear & Greed, sentiment timeseries, earnings history |
| R3-R7 | Risk | Config persistence, margin data, drawdown chart, correlation |

### P2 -- Nice to Have

| ID | Tab | Feature |
|---|---|---|
| P9-P10 | Performance | Trade duration, AI commentary |
| C6-C7 | P&L Calendar | CSV export, day journaling |
| F8-F10 | On-Chain Flow | Sector heatmap viz, WebSocket, watchlist |
| M8-M10 | Macro-Pulse | Sparklines, regime history, event alerts |
| N7-N9 | Narrative | Alert threshold, Reddit, insider trading |
| R8-R10 | Risk | Greeks, stress testing, real-time alerts |

---

## Estimated Effort

- **P0 items (17 tasks):** ~3-4 weeks for 1 developer. Most are S/M complexity -- wiring existing data, fixing mappings, basic calculations.
- **P1 items (23 tasks):** ~6-8 weeks. Mix of M/L tasks requiring new endpoints, charts, and integrations.
- **P2 items (17 tasks):** ~8-12 weeks. Larger features requiring new services, WebSocket infra, external API integrations.

**Recommended approach:** Tackle all P0 items first in a single sprint. The Performance and Risk tabs have the worst ratio of "looks functional but is not" -- users see data that is actually empty or wrong.

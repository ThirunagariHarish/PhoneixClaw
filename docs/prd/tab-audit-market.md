# Market Command Center (/market) -- Deep Audit

**Date:** 2026-04-11
**Auditor:** Nova (PM Agent)
**Page:** `/market` -- `apps/dashboard/src/pages/Market.tsx`

---

## 1. Current State -- Full Widget Catalog

The Market Command Center contains **57 widgets** organized across **10 categories**, managed by a tab-based drag-and-drop grid layout using `react-grid-layout`.

### Architecture Summary

| Aspect | Implementation |
|---|---|
| Grid library | `react-grid-layout` (ResponsiveGridLayout) |
| Breakpoints | lg:12col, md:10col, sm:6col, xs:4col, xxs:2col |
| Row height | 40px |
| Persistence | `localStorage` key `mcc-tabs-v2` |
| Tab system | Custom TabBar with create/rename/duplicate/delete |
| Widget config | Per-widget symbol config via `WidgetSettingsDialog` |
| Catalog UI | Modal dialog with category grouping |

### Widget Classification by Implementation Type

#### A. TradingView Embed Widgets (16 widgets)
These use `TradingViewEmbed.tsx` to inject TradingView's hosted JS widgets. They work independently of the backend.

| ID | Label | Category | Configurable |
|---|---|---|---|
| `tv-chart` | TradingView Chart | Charts | Yes (symbol) |
| `global-indices` | Global Indices | Indices & Performance | No |
| `heatmap` | Market Heatmap | Charts | No |
| `stock-screener` | Stock Screener | Screeners | No |
| `forex-cross-rates` | Forex Cross Rates | Screeners | No |
| `crypto-screener` | Crypto Screener | Screeners | No |
| `technical-analysis` | Technical Analysis | Charts | Yes (symbol) |
| `symbol-info` | Symbol Info | Market Pulse | Yes (symbol) |
| `mini-chart` | Mini Chart | Charts | Yes (symbol) |
| `ticker-tape` | Ticker Tape | Market Pulse | No |
| `top-stories` | Top Stories | News & Social | No |
| `fundamental-data` | Fundamental Data | Screeners | Yes (symbol) |
| `company-profile` | Company Profile | Screeners | Yes (symbol) |
| `crypto-heatmap` | Crypto Heatmap | Charts | No |
| `etf-heatmap` | ETF Heatmap | Charts | No |
| `hotlists` | Hotlists | Trading Intel | No |

#### B. API-Backed Widgets (21 widgets)
These fetch data from `/api/v1/market/*` endpoints. **Critical finding: the backend only exposes `/api/v2/market/` routes with hardcoded stub data (4 endpoints). The 21 widgets hitting `/api/v1/market/*` endpoints have NO corresponding backend routes.**

| ID | Label | API Endpoint | Category |
|---|---|---|---|
| `fear-greed` | Fear & Greed Index | `/api/v1/market/fear-greed` | Market Pulse |
| `vix` | VIX Volatility | TradingView embed | Market Pulse |
| `market-breadth` | Market Breadth | `/api/v1/market/breadth` | Market Pulse |
| `mag7` | Mag 7 Tracker | `/api/v1/market/mag7` | Indices & Performance |
| `sector-perf` | Sector Performance | `/api/v1/market/sectors` | Indices & Performance |
| `futures` | Futures Market | (TradingView embed) | Indices & Performance |
| `top-movers` | Top Movers | `/api/v1/market/top-movers` | Trading Intel |
| `earnings-cal` | Earnings Calendar | (TradingView embed) | Trading Intel |
| `econ-cal` | Economic Calendar | (TradingView embed) | Trading Intel |
| `put-call-ratio` | Put/Call Ratio | `/api/v1/market/put-call-ratio` | Trading Intel |
| `ipo-calendar` | IPO Calendar | `/api/v1/market/ipo-calendar` | Trading Intel |
| `rvol` | Relative Volume | `/api/v1/market/rvol` | Trading Intel |
| `52week` | 52-Week Highs/Lows | `/api/v1/market/52week` | Trading Intel |
| `sector-rotation` | Sector Rotation | `/api/v1/market/sector-rotation` | Indices & Performance |
| `gex` | Gamma Exposure (GEX) | `/api/v1/market/gex` | SPX Day Trading |
| `market-internals` | Market Internals | `/api/v1/market/internals` | SPX Day Trading |
| `vix-term` | VIX Term Structure | `/api/v1/market/vix-term-structure` | SPX Day Trading |
| `premarket-gaps` | Premarket Gap Scanner | `/api/v1/market/premarket-gaps` | SPX Day Trading |
| `spx-levels` | SPX Key Levels | `/api/v1/market/spx-levels` | SPX Day Trading |
| `options-flow` | Options Flow | `/api/v1/market/options-flow` | SPX Day Trading |
| `correlations` | Correlation Matrix | `/api/v1/market/correlations` | SPX Day Trading |
| `volatility` | Volatility Dashboard | `/api/v1/market/volatility` | SPX Day Trading |
| `premarket-movers` | Premarket Movers | `/api/v1/market/premarket-movers` | SPX Day Trading |
| `day-pnl` | Day Trade P&L | `/api/v1/market/day-pnl` | Platform |
| `bond-yields` | Bond Yields | `/api/v1/market/bond-yields` | Assets |

#### C. External Data / News Widgets (5 widgets)
| ID | Label | Data Source | Category |
|---|---|---|---|
| `breaking-news` | Breaking News | `/api/v1/news?limit=20` | News & Social |
| `social-feed` | Political Social Feed | Unknown/custom | News & Social |
| `trending-videos` | Trending Videos | Unknown/custom | News & Social |
| `rss-feed` | RSS News Feed | Unknown/custom | News & Social |
| `platform-sentiment` | Platform Sentiment | Unknown/custom | Platform |

#### D. Pure Frontend / Local Widgets (8 widgets)
These require no backend. They use `localStorage` or are purely computational.

| ID | Label | Storage | Category |
|---|---|---|---|
| `trading-checklist` | Trading Checklist | localStorage | Platform |
| `quick-notes` | Quick Notes | localStorage | Platform |
| `position-calc` | Position Size Calculator | None (stateless) | Tools |
| `risk-reward` | Risk/Reward Visualizer | None (stateless) | Tools |
| `market-clock` | Market Clock | None (live time) | Market Pulse |
| `session-timer` | Trading Sessions | None (live time) | Market Pulse |
| `keyboard-shortcuts` | Keyboard Shortcuts | Unknown | Tools |
| `options-expiry` | Options Expiry | Unknown | Trading Intel |

#### E. Asset-Class Widgets (TradingView Embeds likely)
| ID | Label | Category |
|---|---|---|
| `crypto` | Crypto Overview | Assets |
| `commodities` | Commodities | Assets |
| `forex` | Currency Pairs | Assets |

### Category Breakdown

| Category | Widget Count |
|---|---|
| Market Pulse | 6 |
| Indices & Performance | 5 |
| News & Social | 5 |
| Assets | 4 |
| Trading Intel | 9 |
| Charts | 6 |
| Screeners | 4 |
| SPX Day Trading | 9 |
| Platform | 4 |
| Tools | 3 |

### Tab Management Features
- Create new tabs (start empty)
- Rename tabs (inline edit)
- Duplicate tabs (deep copy)
- Delete tabs (minimum 1 tab enforced)
- Widget count shown per tab
- Sticky tab bar (z-10)
- Default tab: "Overview" with 6 starter widgets

---

## 2. Competitive Research

### TradingView Multi-Chart Layout
- Supports 2-16 charts per layout depending on subscription tier (Essential: 2, Plus: 4, Premium: 8, Pro: 16)
- 40+ layout configuration templates
- **Symbol sync**: All charts can follow the same symbol change; toggled per layout
- **Crosshair sync**: Moving crosshair on one chart shows corresponding time on all others
- **Interval sync**: Can sync timeframes independently from symbol sync
- **Tab color linking**: Color-tag tabs so they follow ticker changes made in any linked tab
- **Drawing sync**: Drawings can be synced across charts
- **Screener-to-chart linking**: Clicking a screener row opens that symbol in a linked chart

Sources: [TradingView Multi-Chart Layouts](https://www.tradingview.com/support/solutions/43000629990-leveraging-multi-chart-layouts-in-your-analysis/), [Symbol Syncing](https://www.tradingview.com/support/solutions/43000673893-symbol-syncing-between-tabs/), [Chart Sync](https://www.tradingview.com/support/solutions/43000761094-how-to-sync-selected-charts/)

### Bloomberg Terminal (Launchpad)
- **No panel limit**: Removed the legacy 4-panel maximum; now supports arbitrary tabs/windows
- **Fully resizable**: Any window can be resized to show more/fewer rows
- **Launchpad**: Dynamic multi-asset security monitors, powerful alerting tools, charts, and market-moving news
- **Worksheets**: Real-time collaborative spreadsheet-style data grids
- **BQuant Apps**: Interactive dashboards with dropdowns and ipywidgets; published as Launchpad components
- **Spotlight**: Curated charts, graphics, and video on major themes
- **Alert system**: Sophisticated cross-asset alerting integrated into every widget

Sources: [Bloomberg Terminal Essentials](https://www.bloomberg.com/professional/insights/technology/bloomberg-terminal-essentials-ib-worksheets-launchpad/), [Bloomberg Launchpad Guide](https://my.lerner.udel.edu/wp-content/uploads/BB-Getting-Started-in-Launchpad.pdf), [Bloomberg Terminal UX](https://www.bloomberg.com/company/stories/how-bloomberg-terminal-ux-designers-conceal-complexity/)

### Industry Best Practices (2025-2026)
- **TradesViz**: 100% control over widget placement, drag-by-empty-area, resize-from-corner, grid-snap; combined chart+statistics widgets showing win/loss ratios, profit factors
- **TailAdmin / NextAdmin**: Stock dashboard templates with Tailwind CSS + Next.js; pre-built chart and table components
- **TradingView Free Widgets**: Embeddable widgets for heatmaps, screeners, tickers, charts -- Phoenix already uses many of these

Sources: [TradesViz Dashboard Widgets](https://www.tradesviz.com/blog/new-custom-dashboard-widgets-2/), [TailAdmin Stock Templates](https://tailadmin.com/blog/stock-market-dashboard-templates), [TradingView Free Widgets](https://www.tradingview.com/widget/)

---

## 3. Gap Analysis

### 3.1 Critical Issue: Backend API Routes Missing

**Severity: P0**

The widgets reference 21+ endpoints under `/api/v1/market/*`, but the backend only has `/api/v2/market/` with 4 stub endpoints returning hardcoded data. This means:

- All API-backed widgets (Fear & Greed, GEX, Market Internals, Options Flow, Correlations, VIX Term Structure, Premarket Gaps, SPX Key Levels, Volatility Dashboard, Day Trade P&L, Top Movers, Mag7, Sector Performance, Bond Yields, 52-Week, Relative Volume, IPO Calendar, Put/Call Ratio, Sector Rotation, Premarket Movers, Market Breadth) will **show loading spinners or "No data" states** until backend routes are implemented.

- The frontend gracefully handles missing data (shows "No data" messages), but users see 21 broken widgets if they add them.

**Recommendation**: Either (a) implement real `/api/v1/market/*` routes, or (b) mark these widgets as "Coming Soon" in the catalog so users do not add non-functional widgets.

### 3.2 Widget-to-Widget Linking: Absent

**Severity: P1**

There is **no cross-widget symbol linking**. Each configurable widget has its own symbol set independently via `WidgetSettingsDialog`. Compared to TradingView (symbol sync, crosshair sync, interval sync, color-tag linking) and Bloomberg (linked security monitors), this is a significant gap.

**Current behavior**: Changing symbol on a TradingView Chart widget requires opening settings, typing a new symbol, and clicking Apply. This does not update the Technical Analysis, Symbol Info, Mini Chart, or any other configurable widget.

**What competitors offer**:
- Click a ticker in Top Movers -> all linked widgets update to that symbol
- Watchlist row click -> chart + TA + fundamentals all switch
- Screener selection -> chart focuses on that symbol
- Crosshair time sync across multiple charts

### 3.3 TradingView Chart Widget -- Hardcoded Exchange

**Severity: P1**

`TradingViewChartWidget.tsx` line 11 hardcodes `NASDAQ:${symbol}`. This means:
- NYSE-listed stocks (e.g., BAC, JPM, WMT) will fail or show wrong data
- Forex pairs, crypto, commodities, ETFs on other exchanges will not work correctly

### 3.4 No Layout Presets / Templates

**Severity: P2**

Users start with one default tab ("Overview" with 6 widgets). There are no pre-built layout templates like:
- "Day Trading Station" (GEX + Market Internals + Premarket + Options Flow + Chart)
- "Macro Overview" (Indices + Bond Yields + Commodities + Forex + VIX Term)
- "Swing Trading" (Screener + Chart + TA + Fundamentals + Earnings Calendar)
- "Options Desk" (Options Flow + GEX + Put/Call + Volatility + Expiry Calendar)

TradingView offers 40+ layout templates. Bloomberg Launchpad offers role-based default layouts.

### 3.5 No Widget Search / Filter in Catalog

**Severity: P2**

The widget catalog modal shows all 57 widgets grouped by category, but has no search box. With 57 widgets, users must scroll through 10 categories to find what they need.

### 3.6 No Drag-to-Reorder in Catalog

**Severity: P2**

Within a tab, widgets can be dragged and resized. But the catalog itself has no concept of "favorites" or "recently used" widgets.

### 3.7 No Widget Refresh / Error States

**Severity: P2**

API-backed widgets show a spinner while loading and "No data" on failure, but there is no:
- Manual refresh button per widget
- Retry on error
- "Last updated" timestamp
- Error message explaining why data is unavailable
- Stale data indicator

### 3.8 Performance Concerns

**Severity: P2**

- TradingView embed widgets inject `<script>` tags directly into the DOM. With 16 possible TV widgets, having more than 5-6 active simultaneously will cause significant memory usage and potential iframe/script conflicts.
- `TradingViewEmbed.tsx` uses `replaceChildren()` on every config change, which destroys and recreates the entire widget DOM.
- The `useEffect` dependency `[configKey || '']` is a string expression, not a proper dependency -- this could cause unexpected re-renders or stale closures.
- All 57 widget components are eagerly imported in `Market.tsx` (no code splitting / lazy loading).

### 3.9 No Widget Maximization / Full-Screen

**Severity: P2**

Widgets can be resized within the grid, but there is no "maximize" or "pop-out" button to view a widget full-screen. Both TradingView and Bloomberg support this.

### 3.10 Tab State -- localStorage Only

**Severity: P2**

All tab layouts, widget selections, and configs are stored in `localStorage`. This means:
- Layouts are lost when clearing browser data
- No cross-device sync
- No sharing layouts between users
- No server-side backup

### 3.11 Missing Widgets Compared to Competitors

| Widget Type | TradingView | Bloomberg | Phoenix | Gap |
|---|---|---|---|---|
| Watchlist | Yes | Yes | No | **Missing** |
| Alert Manager | Yes | Yes | No | **Missing** |
| Order Book / DOM | Yes | Yes | No | **Missing** |
| Trade History Log | Yes | Yes | Partial (Day P&L) | Gap |
| Portfolio Overview | No | Yes | No | **Missing** |
| Earnings Whisper / Estimates | No | Yes | No | **Missing** |
| Dark Pool / Block Trade Prints | No | Yes | No | **Missing** |
| Insider Trading Tracker | No | Yes | No | **Missing** |
| Short Interest / Borrow Rate | No | Yes | No | **Missing** |
| Multi-Timeframe Chart | Yes | Yes | No | **Missing** |
| Drawing Tools / Annotations | Yes | Yes | No | **Missing** |
| Replay / Backtest on Chart | Yes | No | No | **Missing** |

---

## 4. Implementation Proposals

### P0 -- Critical Fixes (Sprint 1)

#### 4.1 Backend Market Data Routes
Implement the 21 missing `/api/v1/market/*` endpoints. Options:
- Real data from external APIs (Alpha Vantage, Yahoo Finance, CBOE, FRED)
- For expensive data (GEX, options flow): cache with 5-min TTL in Redis
- For day-pnl: read from Phoenix's own trades table
- Mark unimplemented widgets as "Coming Soon" in the catalog immediately

#### 4.2 Fix TradingView Chart Exchange Hardcoding
Replace `NASDAQ:${symbol}` with exchange-aware symbol resolution. Either:
- Accept full TradingView symbol format (e.g., "NYSE:BAC")
- Auto-detect exchange from symbol lookup

### P1 -- Widget Linking System (Sprint 2)

#### 4.3 Symbol Context / Linking Groups
Implement a "Link Group" system (inspired by TradingView color tags):
- Each configurable widget can join a link group (color-coded: red, blue, green, none)
- Changing symbol in any widget in a group propagates to all others in that group
- Clicking a ticker in Top Movers, Hotlists, Screener, or Watchlist broadcasts to the active link group
- Use React Context or Zustand store for link group state

#### 4.4 Watchlist Widget
Add a new watchlist widget that:
- Shows user-defined list of symbols with price, change, volume
- Click-to-link: clicking a symbol broadcasts to linked widgets
- Add/remove symbols inline
- Persist to localStorage (and eventually server)

### P2 -- UX Improvements (Sprint 3)

#### 4.5 Layout Presets
Add 4-6 preset layouts accessible from a "Templates" button:
- Day Trading Station
- Macro Overview
- Swing Trading
- Options Desk
- Crypto Focus
- News Room

#### 4.6 Widget Catalog Search
Add a search input at the top of the widget catalog dialog. Filter by label, description, and category as the user types.

#### 4.7 Widget Maximize / Pop-Out
Add a maximize button to `WidgetWrapper` header bar that:
- Expands the widget to fill the viewport (modal overlay)
- Has a close/minimize button to return to grid position
- Optionally: pop-out into a separate browser window

#### 4.8 Widget Refresh & Error Handling
- Add a refresh icon to `WidgetWrapper` for API-backed widgets
- Show "Last updated: Xm ago" in widget footer
- Show retry button on API failure
- Add stale data indicator (amber dot if data > 10 min old)

#### 4.9 Lazy Loading
Convert all 57 widget imports in `Market.tsx` to `React.lazy()` with `Suspense` boundaries. Only load widget code when a widget is actually added to a tab.

#### 4.10 Server-Side Layout Persistence
- Save tab/layout data to a user preferences table in Postgres
- Sync on login, fall back to localStorage for offline
- Enable "Share Layout" feature (generate a shareable layout URL)

### P3 -- Advanced Features (Future)

#### 4.11 Alert Manager Widget
- Set price alerts, volume alerts, technical alerts
- Notifications via browser push, WhatsApp (existing integration), or Discord
- Visual alert history in widget

#### 4.12 Portfolio Widget
- Show current Phoenix positions with live P&L
- Aggregate by sector, strategy, agent
- Link to position detail pages

#### 4.13 Multi-Timeframe Chart Widget
- Show same symbol across 3-4 timeframes in a single widget (e.g., 5m / 15m / 1H / D)
- TradingView embeds support this with layout configs

#### 4.14 Agent Integration Widgets
- Agent Status widget: show running agents, recent decisions, confidence levels
- Signal Feed widget: live stream of incoming Discord signals and agent actions
- Agent P&L widget: per-agent performance attribution

#### 4.15 Dark Pool / Block Trade Widget
- Unusual block prints feed
- Dark pool short volume ratio
- Requires specialized data provider (e.g., Quiver Quant, Unusual Whales)

---

## 5. Widget Status Summary

| Status | Count | Details |
|---|---|---|
| Fully Working (TradingView embeds) | 16 | Reliable, no backend needed |
| Fully Working (Local/Frontend) | 8 | Checklist, Notes, Calculators, Clocks |
| Broken (No Backend Route) | ~21 | API returns 404; shows "No data" |
| Partially Working | ~5 | News/Social widgets depend on external APIs that may or may not be configured |
| **Total** | **57** (including 7 overlap in classification) | |

---

## 6. Open Questions (Need User Input)

1. **Data provider budget**: Which external market data APIs are you willing to pay for? (Alpha Vantage free tier, Yahoo Finance, CBOE options data, FRED, Unusual Whales, etc.)
2. **Priority between fixing existing broken widgets vs. adding new ones**: Should we focus on making the 21 API-backed widgets functional first, or add missing high-value widgets (Watchlist, Alerts)?
3. **Server-side persistence priority**: Is cross-device layout sync important now, or is localStorage acceptable for the near term?
4. **TradingView embed limits**: Are there any TradingView terms-of-service concerns with embedding 16+ widgets on a single page for a commercial product?
5. **Target user profile for presets**: Which preset layouts matter most? (Day trader? Swing trader? Options trader? Macro/portfolio manager?)

---

## 7. Sources

- [TradingView Multi-Chart Layouts](https://www.tradingview.com/support/solutions/43000629990-leveraging-multi-chart-layouts-in-your-analysis/)
- [TradingView Symbol Syncing Between Tabs](https://www.tradingview.com/support/solutions/43000673893-symbol-syncing-between-tabs/)
- [TradingView Sync Selected Charts](https://www.tradingview.com/support/solutions/43000761094-how-to-sync-selected-charts/)
- [TradingView Charting Library Release Notes](https://www.tradingview.com/charting-library-docs/latest/releases/release-notes/)
- [Bloomberg Terminal Essentials: IB, Worksheets & Launchpad](https://www.bloomberg.com/professional/insights/technology/bloomberg-terminal-essentials-ib-worksheets-launchpad/)
- [Bloomberg Launchpad Getting Started](https://my.lerner.udel.edu/wp-content/uploads/BB-Getting-Started-in-Launchpad.pdf)
- [Bloomberg Terminal UX: Concealing Complexity](https://www.bloomberg.com/company/stories/how-bloomberg-terminal-ux-designers-conceal-complexity/)
- [TradesViz Custom Dashboard Widgets](https://www.tradesviz.com/blog/new-custom-dashboard-widgets-2/)
- [TailAdmin Stock Market Dashboard Templates](https://tailadmin.com/blog/stock-market-dashboard-templates)
- [TradingView Free Financial Widgets](https://www.tradingview.com/widget/)
- [TradingView Widget Collection Docs](https://www.tradingview.com/widget-docs/widgets/)

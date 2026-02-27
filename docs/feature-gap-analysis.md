# Feature Gap Analysis & Enhancement Plan

## Codebase Audit Summary

**Total Services:** 19 | **Fully Functional:** 14 | **Stubs:** 3 | **Partial:** 2
**Database Models:** 25 | **Frontend Pages:** 27 | **Market Widgets:** 25

---

## Feature Inventory (30 models, 19 services)

| # | Feature | Status | Gap |
|---|---------|--------|-----|
| 1 | Authentication & MFA | Complete | -- |
| 2 | User Management & RBAC | Complete | -- |
| 3 | Data Sources (Discord) | Complete | -- |
| 4 | Data Sources (Twitter) | **Stub** | No implementation |
| 5 | Data Sources (Reddit) | **Stub** | No implementation |
| 6 | Trade Pipeline Management | Complete | -- |
| 7 | Trade Parsing (regex+NLP) | Complete | -- |
| 8 | **Signal Scoring** | **Stub** | Empty service, no algorithm |
| 9 | Trade Gateway (approval) | Complete | -- |
| 10 | Trade Execution (Alpaca) | Complete | Only Alpaca, no IBKR |
| 11 | Position Monitoring | Complete | -- |
| 12 | Backtesting | Complete | -- |
| 13 | Sentiment Analysis | Complete | -- |
| 14 | News Aggregation | Complete | -- |
| 15 | AI Trade Recommendations | Complete | -- |
| 16 | Option Chain Analysis | Complete | -- |
| 17 | Strategy Builder (Agent) | Complete | -- |
| 18 | Advanced Pipeline Builder | Complete | -- |
| 19 | Market Command Center | Complete | Widgets connected |
| 20 | Notifications | Complete | -- |
| 21 | Sprint Board | Complete | -- |
| 22 | Model Hub | Complete | -- |
| 23 | **Analytics** | **Basic** | Only 3 charts, no risk metrics |
| 24 | Watchlist | Basic | No price alerts |
| 25 | Chat Widget | Complete | -- |
| 26 | Audit Trail | Complete | -- |
| 27 | Daily Metrics | Complete | -- |
| 28 | Analyst Performance | **Schema only** | No UI, no computation |

---

## Architecture Milestones

### Milestone 1: Signal Scorer Service
**Priority:** Critical (missing pipeline link)
**Research:** Inspired by TradeLabs AI scoring, Probability Trader Pro calibrated confidence

Build a Kafka consumer that:
- Consumes `parsed-trades` before trade-gateway
- Scores each signal (0-100) based on: analyst track record, sentiment alignment,
  market conditions, historical accuracy
- Publishes `scored-trades` with confidence metadata
- Stores scores in AnalystPerformance table

### Milestone 2: Enhanced Analytics Dashboard
**Priority:** High (basic → professional)
**Research:** Inspired by tastytrade, thinkorswim, Interactive Brokers PortfolioAnalyst

Add to Analytics page:
- KPI summary cards (Total P&L, Sharpe, Max DD, Win Rate, Expectancy)
- Performance by ticker (bar chart)
- Trade distribution by hour/day of week (heatmap)
- Risk metrics over time (Sharpe, Sortino trends)
- Streak analysis (consecutive W/L)
- Holding time analysis
- P&L histogram

### Milestone 3: Configuration & Database Cleanup
**Priority:** Medium

- Add missing env vars to .env.example
- Fix AnalystPerformance: add computation logic
- Clean up empty `pass` exception handlers

### Milestone 4: E2E Regression Test Suite
**Priority:** Required

Create comprehensive .md files documenting manual E2E test cases for:
- Authentication flow
- Pipeline creation & execution
- Trade lifecycle
- Analytics & reporting
- Market Command Center
- Strategy Builder

# E2E Regression: Analytics & Reporting

## Prerequisites
- At least 7 days of trading data in daily_metrics table

---

## TC-ANALYTICS-001: Analytics Dashboard Load
**Steps:**
1. Navigate to Analytics page

**Expected:**
- KPI summary row shows 6 cards: Total P&L, Win Rate, Sharpe Ratio, Max Drawdown, Profit Factor, Avg Duration
- Time range selector shows 7d/30d/90d buttons
- All charts render without errors

---

## TC-ANALYTICS-002: Time Range Toggle
**Steps:**
1. On Analytics page, click "7d" button
2. Click "30d" button
3. Click "90d" button

**Expected:**
- Charts update with correct date ranges
- Active button is highlighted
- Data fetched from API with correct `days` parameter

---

## TC-ANALYTICS-003: Cumulative P&L Chart
**Steps:**
1. View the Cumulative P&L chart

**Expected:**
- Area chart with gradient fill
- Shows running total over selected period
- $ formatting on Y-axis
- Hover tooltip shows date and value

---

## TC-ANALYTICS-004: Performance by Ticker
**Steps:**
1. View Performance by Ticker chart

**Expected:**
- Horizontal bar chart sorted by P&L
- Green bars for profitable tickers, red for unprofitable
- Ticker labels on Y-axis

---

## TC-ANALYTICS-005: Win/Loss Streak Chart
**Steps:**
1. View Win/Loss Streak chart

**Expected:**
- Bar chart showing consecutive win/loss days
- Green bars above zero (winning streaks)
- Red bars below zero (losing streaks)

---

## TC-ANALYTICS-006: P&L Distribution Histogram
**Steps:**
1. View P&L Distribution chart

**Expected:**
- Histogram with 12 bins
- Shows distribution shape of daily P&L
- Proper axis labels

---

## TC-ANALYTICS-007: Empty State
**Steps:**
1. View Analytics page with no trading data

**Expected:**
- "No analytics data yet" message displayed
- No chart rendering errors

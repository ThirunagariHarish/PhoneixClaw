# E2E Regression: Sentiment Analysis & News

## Prerequisites
- Sentiment analyzer service running
- News aggregator service running
- At least one data source with sentiment data

---

## TC-SENT-001: Traders Pulse Overview
**Steps:**
1. Navigate to Traders Pulse (Sentiment)

**Expected:**
- Ticker list with sentiment badges
- Search bar functional
- Filter by sentiment works (Very Bullish → Very Bearish)
- Time range filter works (1h to 7d)

---

## TC-SENT-002: Ticker Detail Modal
**Steps:**
1. Click on a ticker in the sentiment list

**Expected:**
- Modal opens with:
  - AI-generated ticker summary
  - Sentiment score and trend
  - Message list from all sources
  - Watchlist add/remove button

---

## TC-SENT-003: Sentiment Alerts
**Steps:**
1. Click "Alerts" button in Traders Pulse
2. Create a new alert (e.g., AAPL sentiment crosses bullish)
3. Save

**Expected:**
- Alert created and listed
- Alert toggleable (enable/disable)
- Alert deletable

---

## TC-NEWS-001: Trending News
**Steps:**
1. Navigate to Trending News

**Expected:**
- Headlines grouped by date (Today, Yesterday, etc.)
- Source badges (Finnhub, NewsAPI, etc.)
- Sentiment indicators on each headline
- External links open in new tab

---

## TC-NEWS-002: News Source Filter
**Steps:**
1. Select a specific source from filter dropdown
2. Enter a ticker in search

**Expected:**
- Headlines filtered by source
- Ticker filter narrows results
- Results update live

---

## TC-NEWS-003: News Connections
**Steps:**
1. Click "Manage Connections" in Trending News
2. Add a new news API connection
3. Toggle and delete connections

**Expected:**
- Connection dialog opens
- New connection created
- Toggle enables/disables polling
- Delete removes the connection

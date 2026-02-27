# E2E Regression: Market Command Center

## Prerequisites
- Application running with all backend services

---

## TC-MCC-001: Initial Load
**Steps:**
1. Navigate to Market Command Center

**Expected:**
- Default widgets loaded (Fear & Greed, Global Indices, Top Movers, Breaking News, Mag7, Sector Performance)
- Grid layout renders correctly
- Drag handles visible on each widget

---

## TC-MCC-002: Widget Drag & Drop
**Steps:**
1. Grab a widget by its drag handle
2. Move it to a different position
3. Release

**Expected:**
- Widget moves to new position
- Other widgets reflow
- Layout persisted (survives page refresh)

---

## TC-MCC-003: Widget Resize
**Steps:**
1. Grab the resize handle (bottom-right corner of a widget)
2. Drag to resize

**Expected:**
- Widget resizes
- Content adapts to new size
- Minimum size constraints respected

---

## TC-MCC-004: Add Widget
**Steps:**
1. Click "Add Widget" button
2. Browse the widget catalog
3. Select a widget (e.g., "Crypto")
4. Close the catalog

**Expected:**
- New widget appears at the bottom of the grid
- Widget catalog shows it as already added (disabled)
- Widget fetches and displays data

---

## TC-MCC-005: Remove Widget
**Steps:**
1. Click the X button on a widget header

**Expected:**
- Widget removed from grid
- Layout updated
- Widget available again in catalog

---

## TC-MCC-006: Layout Persistence
**Steps:**
1. Customize layout (move, resize, add/remove widgets)
2. Refresh the page

**Expected:**
- Layout restored exactly as left
- Same widgets in same positions and sizes

---

## TC-MCC-007: Widget Data Loading
**Steps:**
1. Check each API-connected widget:
   - Fear & Greed Index: shows score 0-100
   - Mag7: shows 7 tech stock prices
   - Top Movers: shows gainers/losers
   - Breaking News: shows recent headlines
   - Sector Performance: shows sector bars
   - Bond Yields: shows treasury yields
   - Market Breadth: shows advance/decline
   - Platform Sentiment: shows ticker sentiment

**Expected:**
- Each widget shows real data from backend APIs
- Loading spinners during fetch
- Error states if API unavailable

---

## TC-MCC-008: TradingView Embeds
**Steps:**
1. Add TradingView chart widget
2. Add Heatmap widget
3. Add Crypto widget (TradingView)

**Expected:**
- TradingView embeds load correctly
- Interactive features work (zoom, scroll)
- Theme matches application theme

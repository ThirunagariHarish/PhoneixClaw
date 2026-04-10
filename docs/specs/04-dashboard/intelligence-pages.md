# Spec: Intelligence Dashboard Pages

## Purpose

Six dashboard pages provide market intelligence, sentiment analysis, and risk monitoring. They currently use mock data. This spec defines real data sources, backend APIs, caching, and persistence so the frontend can switch to live endpoints under `/api/v2/intelligence/*`.

## Pages Overview

| Page | Current State | Data Source |
|------|---------------|-------------|
| Daily Signals | Mock data | Discord ingestion pipeline |
| Macro Pulse | Mock data | FRED API + yfinance |
| 0DTE SPX | Mock data | yfinance options chain |
| On-Chain Flow | Mock data | Public blockchain APIs |
| Narrative Sentiment | Mock data | News API + social |
| Risk Compliance | Mock data | Portfolio DB + calculations |

---

## Page 1: Daily Signals

### Data Source

Real signal pipeline from Discord ingestion: `channel_messages` table plus agent processing results (parsed signals, model outputs, execution outcomes).

### API Endpoint

```
GET /api/v2/intelligence/signals?date=2026-04-03
```

Query parameters:

- `date` (optional): ISO date; default today in exchange timezone (e.g. America/New_York).

### Response

```json
{
    "date": "2026-04-03",
    "signals": [
        {
            "id": "sig_001",
            "timestamp": "2026-04-03T10:15:00Z",
            "channel": "spx-alerts",
            "analyst": "Vinod",
            "ticker": "SPY",
            "side": "buy",
            "price": 450.00,
            "confidence": 0.78,
            "model_prediction": "TRADE",
            "action_taken": "executed",
            "pnl": 125.00
        }
    ],
    "summary": {
        "total_signals": 15,
        "executed": 8,
        "skipped": 7,
        "win_rate": 0.625,
        "daily_pnl": 340.00
    }
}
```

Field notes:

- `model_prediction`: enum such as `TRADE`, `SKIP`, `HOLD` (align with agent output schema).
- `action_taken`: `executed`, `skipped`, `pending`, etc.
- `pnl`: realized P&L for executed trades for that signal when applicable; null or omitted if not executed.

### Backend

- Query `agent_trades` and `agent_metrics`; join with `channel_messages` (or derived signal rows) for raw signal context (channel, message id, analyst if available).
- Filter by `date` on signal timestamp or trade open time, per product decision.
- Aggregate `summary` from the same filtered set.

### Errors

- `400` invalid date format.
- `503` if DB unavailable.

---

## Page 2: Macro Pulse

### Data Source

- **FRED API** (Federal Reserve Economic Data): free; requires API key stored in secrets/config.
- **yfinance**: real-time or near-real-time quotes for market indices and derived series where applicable.

### Indicators

| Indicator | Source | Update Frequency |
|-----------|--------|------------------|
| S&P 500 | yfinance (^GSPC) | Real-time |
| VIX | yfinance (^VIX) | Real-time |
| 10Y Treasury | FRED (DGS10) | Daily |
| Fed Funds Rate | FRED (FEDFUNDS) | Monthly |
| CPI YoY | FRED (CPIAUCSL) | Monthly |
| Unemployment | FRED (UNRATE) | Monthly |
| GDP Growth | FRED (GDP) | Quarterly |
| Put/Call Ratio | yfinance / CBOE | Daily |

CPI YoY should be computed from series (year-over-year percent change) in the service layer, not assumed as a raw FRED field unless using a precomputed series ID.

### API Endpoint

```
GET /api/v2/intelligence/macro
```

Optional query parameters:

- `refresh`: if supported, bypass cache for admin/debug only.

### Response Shape (illustrative)

Single JSON object grouping `realtime` (indices, VIX), `fred` (latest values + observation dates), and `metadata` (last fetch times, cache TTL). Exact field names should match dashboard components during implementation.

### Backend

- **Scheduled job** (daily at 8:00 AM ET): fetch FRED series, normalize units and dates, write to Redis (or DB) with 24-hour TTL for slow-moving series.
- **On request**: fetch real-time indices from yfinance with **60-second** cache in Redis or in-process LRU.
- **macro_fetcher** service (`apps/api/src/services/macro_fetcher.py`): encapsulate FRED client, yfinance calls, parsing, and cache keys.

### Errors

- Partial success: return cached stale data with `stale: true` if upstream fails (optional product decision).
- `503` if no cache and all sources fail.

---

## Page 3: 0DTE SPX

### Data Source

yfinance for SPX (or `^SPX` / mapped symbol) options chain. If production requires broker-level quotes, `robin_stocks` or another execution connector may supplement; spec assumes yfinance as primary unless compliance restricts it.

### Features

- Current SPX price and intraday chart (chart data can be a separate lightweight endpoint or embedded in the same response; prefer split if payloads grow large).
- 0DTE options chain: calls and puts at strikes near spot (configurable window, e.g. ±N strikes or ±X%).
- **Max pain**: strike minimizing total option holder loss at expiry; compute server-side from open interest by strike.
- **Unusual volume**: flag contracts where volume > 3× average open interest (or 3× a rolling average volume; define one rule and document in code).
- **GEX (gamma exposure) estimate**: approximate from chain OI, greeks if available, or simplified model; document assumptions in service docstring.

### API Endpoint

```
GET /api/v2/intelligence/0dte?ticker=SPX
```

- `ticker`: default `SPX`; allow `SPXW` or index proxy if product requires.

### Backend

- Fetch chain via yfinance (or `robin_stocks`); **cache per underlying + expiry bucket for 30 seconds** to avoid hammering upstream.
- Compute max pain, unusual volume, and GEX in `intelligence` route handlers or a dedicated `options_intelligence` service module.
- Rate-limit public endpoint if exposed beyond internal dashboard.

---

## Page 4: On-Chain Flow

### Data Source

- Public blockchain APIs (Etherscan, blockchain.com, or similar) for supplementary on-chain stats if needed.
- **Whale Alert API** (free tier: 10 requests/minute).

### Features

- Large BTC/ETH transfers (threshold e.g. > $1M USD equivalent at time of observation).
- Exchange inflow/outflow trends (aggregated over windows).
- Whale wallet activity (labels depend on Whale Alert / third-party data).

### API Endpoint

```
GET /api/v2/intelligence/onchain
```

Query parameters (optional):

- `hours`: default 24; cap at 168 for weekly view.

### Backend

- **Scheduled poller** every 5 minutes: call Whale Alert, normalize events, upsert into `onchain_events` table (idempotent on external transaction id).
- Dashboard reads last N hours from `onchain_events`; no direct third-party call from the request path in steady state.

### Priority

Lower than other pages. **MVP**: show "Coming Soon" or empty state with structured placeholder response until poller and table exist.

---

## Page 5: Narrative Sentiment

### Data Source

- **NewsAPI** (free tier: 100 requests/day): financial headlines for tracked tickers and general market.
- **Reddit API**: subreddits such as r/wallstreetbets, r/stocks for post titles/comments samples and coarse sentiment.
- **Twitter/X**: skip initially due to API cost and policy constraints.

### Features

- Top news headlines affecting tracked tickers.
- Sentiment score per ticker: bullish / bearish / neutral (numeric score −1..1 or 0..100 plus label).
- Trending topics (entities or hashtags aggregated over the window).

### API Endpoint

```
GET /api/v2/intelligence/sentiment?tickers=SPY,QQQ,AAPL
```

- `tickers`: comma-separated; cap count to respect quotas (e.g. max 20).

### Backend

- **Scheduled** (every 30 minutes): fetch news (and Reddit batch), run sentiment classification (TextBlob for baseline; optional FinBERT for higher quality in GPU or batch worker).
- Persist **`sentiment_snapshots`** rows: ticker, timestamp, aggregate score, headline count, top headlines JSON, source breakdown.
- **GET** returns latest snapshot per requested ticker plus optional sparkline from last 24h if stored.

### Quota Management

- Centralize API keys; track daily NewsAPI usage in Redis or DB to avoid hard failures mid-day.

---

## Page 6: Risk Compliance

### Data Source

Real portfolio data from the database: `positions`, `agent_trades`, `agent_metrics` (and any existing portfolio snapshot tables). If `positions` is not yet modeled, derive from latest known state from trades + cash ledger per existing schema.

### Features

- Current portfolio exposure by sector (sector mapping from instrument master or external static map).
- Position concentration: percent of portfolio in each position.
- Daily P&L versus configured limits.
- **VaR** (Value at Risk) estimate, e.g. 95% 1-day from rolling 20-day returns on portfolio or proxy.
- Drawdown from peak (portfolio equity curve).
- Margin utilization (if margin accounts exist in schema; else omit or zero).
- Rule violations: positions or exposures exceeding limits (list of structured violations).

### API Endpoint

```
GET /api/v2/intelligence/risk
```

### Response

```json
{
    "portfolio_value": 50000.00,
    "cash": 15000.00,
    "exposure_pct": 70.0,
    "positions": [
        {"ticker": "SPY", "weight_pct": 25.0, "pnl": 500.00}
    ],
    "risk_metrics": {
        "daily_var_95": -750.00,
        "max_drawdown_pct": -5.2,
        "sharpe_ratio": 1.5,
        "current_daily_pnl": 340.00,
        "daily_pnl_limit": 500.00,
        "daily_loss_limit": -200.00
    },
    "violations": []
}
```

`violations` entries should be objects: `code`, `message`, `severity`, `ticker` (optional), `value`, `limit`.

### Backend

- Aggregate realized P&L from `agent_trades`; unrealized from mark-to-market on open positions (price source: same as rest of platform).
- Historical metrics from `agent_metrics` for Sharpe, drawdown, and return series.
- **VaR**: rolling 20-day portfolio returns; parametric or historical bootstrap; document method in code.
- Limits: read from config or `risk_limits` table if introduced later.

---

## Implementation Priority

1. **Daily Signals** — highest value; uses existing ingestion and agent tables.
2. **Risk Compliance** — critical for live trading safety.
3. **Macro Pulse** — broad context; FRED + yfinance are straightforward with caching.
4. **0DTE SPX** — useful for options-oriented agents; depends on chain quality from yfinance.
5. **Narrative Sentiment** — nice to have; quota and model cost tradeoffs.
6. **On-Chain Flow** — lowest priority; acceptable as "Coming Soon" initially.

---

## Files to Create

| File | Action |
|------|--------|
| `apps/api/src/routes/intelligence.py` | New — register all six page endpoints; delegate to services. |
| `apps/api/src/services/macro_fetcher.py` | New — FRED + yfinance, caching. |
| `apps/api/src/services/sentiment_analyzer.py` | New — headline fetch, classification, snapshot persistence. |

Additional files likely needed during implementation (not exhaustive):

- `apps/api/src/services/options_chain.py` or inline in intelligence service for 0DTE math.
- `shared/db/models/onchain_event.py`, migration for `onchain_events`.
- `shared/db/models/sentiment_snapshot.py`, migration for `sentiment_snapshots`.
- Register router in `apps/api/src/main.py` under prefix `/api/v2/intelligence`.

---

## Cross-Cutting Concerns

- **Authentication**: same as other dashboard APIs (session or bearer); intelligence endpoints may be internal-only first.
- **Versioning**: `/api/v2/` keeps mock v1 and live v2 side by side during migration.
- **Observability**: log upstream latency and cache hit/miss per endpoint; metric for Whale Alert and NewsAPI quota.
- **Configuration**: API keys and limits via environment variables or secrets manager; document in deployment README only if the repo already documents env vars elsewhere.

---

## Open Questions

- Canonical timezone for `date` on Daily Signals (exchange vs UTC).
- Whether `analyst` is always derivable from Discord user metadata or requires a mapping table.
- Exact schema for `positions` if not yet aligned with `agent_trades`.
- Put/call ratio: definitive symbol and fallback when CBOE data is missing.

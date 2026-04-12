# PRD: Feature Engineering Expansion (~200 to ~335-365 features)

## 1. Problem

Phoenix's enrichment pipeline currently computes approximately 200 features across 8 categories (price action, technical indicators, moving averages, volume, market context, time features, sentiment/events, and options data). Both the backtesting pipeline (`agents/backtesting/tools/enrich.py`) and the live trading pipeline (`agents/templates/live-trader-v1/tools/enrich_single.py`) share this feature set.

Key gaps in the current feature set:

- **Dark pool and institutional flow data** is absent. The existing Unusual Whales client (`shared/unusual_whales/client.py`) only covers options flow, GEX, and option chains. Dark pool activity, congressional trading, insider transactions, short interest, institutional ownership, and volatility surface data are unavailable despite the API supporting them.
- **Gap analysis** is minimal. The pipeline computes a single `gap_pct` value but lacks gap-fill tracking, persistence scoring, or historical gap statistics that are critical for mean-reversion and momentum strategies.
- **News sentiment** is not captured. There is no news client. The only text-based signal is FinBERT sentiment from Discord messages, which reflects analyst opinion rather than market-moving headlines.
- **Company event calendars** beyond basic earnings/FOMC/CPI/NFP proximity flags are missing. There is no coverage of dividend events, stock splits, SEC insider filings (Form 4), institutional 13F changes, analyst revisions, FDA catalysts, or M&A activity.
- **Data source diversity** is low. The pipeline relies almost entirely on yfinance for price data and a single Unusual Whales integration for options. There is no fallback chain, no cross-source validation, and no social sentiment from Finnhub, Polygon, or Alpha Vantage.

These gaps reduce model accuracy for event-driven trades, limit the pipeline's ability to detect institutional positioning, and create single-point-of-failure risk on yfinance.

## 2. Target Users and Jobs-to-be-Done

| User | Job-to-be-Done |
|------|---------------|
| **Backtesting agent** | Enrich historical trade rows with 335-365 features so ML models train on a richer signal set, improving prediction accuracy for TRADE/SKIP decisions. |
| **Live trading agent** | Compute the same expanded feature set in real time for incoming signals so that live inference matches backtested model expectations (no train/serve skew). |
| **Position monitor agent** | Access institutional flow, dark pool, and news sentiment features to make better exit decisions on open positions. |
| **Platform operator (Harish)** | Manage API keys for new data sources through env vars and see connector status in the dashboard connectors tab. |

## 3. Goals and Non-Goals

### Goals

- Expand the feature set from ~200 to ~335-365 features across 5 new/expanded categories.
- Maintain exact feature parity between the backtesting enrichment pipeline and the live single-trade enrichment pipeline.
- Integrate 4 external data providers (Finnhub, Alpha Vantage, Polygon, Unusual Whales expanded endpoints) plus SEC EDGAR.
- Ensure zero crashes from missing data -- every new feature returns `np.nan` on failure.
- Build a source orchestrator with fallback chains so no single API outage blocks enrichment.
- Add unit tests for every new client module.

### Non-Goals

- Retraining existing models (that is a downstream task after features ship).
- Changing the ML pipeline architecture or model selection logic.
- Building a dashboard UI for feature exploration or monitoring (future work).
- Real-time streaming of features (batch and on-demand only).
- Replacing yfinance as the primary price data source.

## 4. Success Metrics

| Metric | Target |
|--------|--------|
| Feature count after expansion | 335-365 total features |
| Backtest/live feature parity | 100% -- identical feature names and computation logic |
| NaN-safety | 0 crashes when any external API is unavailable |
| API graceful degradation | Pipeline completes enrichment even with 0 of 4 new API keys configured |
| Unit test coverage for new clients | 1 test file per new client, all passing |
| Lint compliance | `make lint` passes with zero errors |

## 5. User Stories

### US-1: Unusual Whales Full Integration (Category D)
**As a** backtesting/live agent, **I want** dark pool, congressional, insider, short interest, institutional, and vol surface features from Unusual Whales, **so that** models can detect institutional positioning and smart money signals.

- **Priority:** P0
- **Acceptance Criteria:**
  - Given the `UNUSUAL_WHALES_API_TOKEN` env var is set, when enrichment runs, then 35-40 new features are computed from 6 UW endpoint groups.
  - Given the API token is missing or an endpoint returns an error, when enrichment runs, then all UW features default to `np.nan` and the pipeline continues.
  - Given a ticker is enriched, when dark pool data is available, then `darkpool_volume_pct`, `darkpool_block_count`, `darkpool_avg_block_size`, `darkpool_net_sentiment`, and `darkpool_lit_ratio` are populated.
- **Dependencies:** Existing `shared/unusual_whales/client.py` (extend, do not replace).

### US-2: Time Series Gap Analysis (Category A)
**As a** backtesting/live agent, **I want** detailed gap analysis features including fill rates, persistence, and z-scores, **so that** models can identify mean-reversion and gap-fade opportunities.

- **Priority:** P0
- **Acceptance Criteria:**
  - Given OHLCV data is available, when enrichment runs, then 15-20 gap analysis features are computed from price data alone (no external API needed).
  - Given fewer than 20 days of history, when gap features are computed, then all gap features return `np.nan`.
  - Given the feature `gap_pct` already exists in the pipeline, when gap analysis is added, then the existing `gap_pct` value remains unchanged and new features are additive.
- **Dependencies:** None (computed from existing yfinance data).

### US-3: News and Headlines Sentiment (Category C)
**As a** backtesting/live agent, **I want** news sentiment features from multiple providers with automatic fallback, **so that** models can factor in market-moving headlines and news momentum.

- **Priority:** P1
- **Acceptance Criteria:**
  - Given at least one of `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY`, or `POLYGON_API_KEY` is set, when enrichment runs, then 25-30 news sentiment features are computed.
  - Given all news API keys are missing, when enrichment runs, then all news features default to `np.nan`.
  - Given Finnhub is unavailable, when the news client attempts a fetch, then it falls back to Alpha Vantage, then Polygon.
  - Given news data is returned, when features are computed, then sector-level and market-level sentiment aggregates are included.
- **Dependencies:** New `shared/data/news_client.py`.

### US-4: Company Events (Category B)
**As a** backtesting/live agent, **I want** comprehensive company event features covering earnings, dividends, splits, insider/institutional activity, analyst consensus, and biotech catalysts, **so that** models can anticipate event-driven price moves.

- **Priority:** P1
- **Acceptance Criteria:**
  - Given a ticker and entry date, when enrichment runs, then 40-50 company event features are computed using available data sources.
  - Given SEC EDGAR is used for insider data, when requests are made, then a valid `SEC_USER_AGENT` header is included per SEC fair access policy.
  - Given earnings data is available, when features are computed, then `days_to_earnings`, `earnings_surprise_last`, `earnings_beat_rate_4q`, and `post_earnings_drift_avg` are populated.
  - Given a stock is not biotech, when biotech features are computed, then `is_biotech` is 0 and `days_to_fda_date` and `fda_catalyst_flag` are `np.nan`.
- **Dependencies:** New `shared/data/company_events.py`, `shared/data/sec_client.py`.

### US-5: Data Source Expansion and Orchestration (Category E)
**As a** backtesting/live agent, **I want** multiple data source clients with a centralized source manager providing fallback chains and cross-source validation, **so that** enrichment is resilient to any single provider outage.

- **Priority:** P1
- **Acceptance Criteria:**
  - Given multiple API keys are configured, when enrichment runs, then `data_source_count`, `data_freshness_score`, and `cross_source_agreement` meta-features are populated.
  - Given a primary source fails, when the source manager attempts a fetch, then it automatically tries the next source in the fallback chain.
  - Given all sources fail, when meta-features are computed, then they default to `np.nan`.
  - Given the Finnhub API is available, when social sentiment is fetched, then `finnhub_social_sentiment` and `reddit_mentions_24h` are populated.
- **Dependencies:** New `shared/data/finnhub_client.py`, `shared/data/polygon_client.py`, `shared/data/alpha_vantage_client.py`, `shared/data/source_manager.py`.

### US-6: Pipeline Parity
**As a** platform operator, **I want** both `enrich.py` (backtesting) and `enrich_single.py` (live) to produce identical feature sets, **so that** there is no train/serve skew.

- **Priority:** P0
- **Acceptance Criteria:**
  - Given both pipelines run on the same ticker and date, when features are compared, then the feature names and computation logic are identical.
  - Given a new feature is added to one pipeline, when the PR is reviewed, then it must also be present in the other pipeline.
- **Dependencies:** All categories above.

### US-7: Configuration and Dependencies
**As a** platform operator, **I want** new API keys managed through env vars, new Python dependencies declared in `pyproject.toml`, and placeholder connector entries for the dashboard, **so that** setup is straightforward.

- **Priority:** P0
- **Acceptance Criteria:**
  - Given the env vars `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `POLYGON_API_KEY`, `UNUSUAL_WHALES_API_TOKEN`, and `SEC_USER_AGENT` are documented, when a new developer sets up the project, then they can configure all data sources.
  - Given new dependencies are added, when `pip install -e .` runs, then all new client libraries are installed.
  - Given `make lint` is run after all changes, when the linter executes, then zero errors are reported.

## 6. Feature Specifications

### 6.1 Category D: Unusual Whales Full Integration (~35-40 features)

**Scope:** Expand `shared/unusual_whales/client.py` with 6 new endpoint groups. Add corresponding Pydantic models to `shared/unusual_whales/models.py`.

| Endpoint Group | API Path | Features |
|---------------|----------|----------|
| Dark Pool | `/api/darkpool/{ticker}` | `darkpool_volume_pct`, `darkpool_block_count`, `darkpool_avg_block_size`, `darkpool_net_sentiment`, `darkpool_lit_ratio` |
| Congressional Trading | `/api/congress/trades` | `congress_buy_count_30d`, `congress_sell_count_30d`, `congress_net_trades_30d`, `congress_total_value_30d` |
| Insider Trading | `/api/insider/trades/{ticker}` | `insider_buy_count_90d`, `insider_sell_count_90d`, `insider_net_shares_90d`, `insider_buy_sell_ratio`, `insider_latest_days_ago` |
| Short Interest | `/api/stock/{ticker}/short-interest` | `short_interest_pct`, `short_interest_days_to_cover`, `short_utilization`, `short_interest_change_30d` |
| Institutional | `/api/stock/{ticker}/institutional` | `institutional_ownership_pct`, `institutional_count`, `institutional_net_change_qtr`, `top10_concentration` |
| Vol Surface | `/api/stock/{ticker}/vol-surface` | `iv_term_structure_slope`, `iv_skew_25d`, `vol_surface_atm_30d`, `vol_surface_atm_60d`, `vol_smile_curvature`, `iv_term_spread_30_60` |

**Client pattern:** Async methods on existing `UnusualWhalesClient`. Each method returns a typed Pydantic model. Responses cached via existing `UWCache` (Redis + memory). Graceful degradation: return `None` on HTTP error, caller maps to `np.nan`.

### 6.2 Category A: Time Series Gap Analysis (~15-20 features)

**Scope:** New module `shared/data/gap_analysis.py` with a pure function `compute_gap_features(open, close, high, low) -> dict`.

| Feature | Description |
|---------|-------------|
| `gap_pct` | Today's open vs yesterday's close (already exists -- preserve) |
| `gap_direction` | 1 (gap up), -1 (gap down), 0 (no gap) |
| `gap_filled_pct` | Percentage of gap filled during session |
| `gap_fill_time_bars` | Bars until gap fill (np.nan if not filled) |
| `avg_gap_fill_rate_20d` | Rolling 20d average of gap fill percentage |
| `gap_persistence_score` | Fraction of gap remaining at close, averaged over 20d |
| `gap_above_avg` | Binary: today's gap > 20d avg gap |
| `consecutive_gap_days` | Count of consecutive same-direction gaps |
| `gap_faded_pct` | Fraction of gaps that reversed direction intraday (20d) |
| `gap_continuation_pct` | Fraction of gaps that continued in gap direction (20d) |
| `avg_gap_size_20d` | Mean absolute gap over 20 days |
| `gap_std_20d` | Std dev of gap sizes over 20 days |
| `gap_zscore` | Today's gap normalized by 20d mean/std |
| `max_gap_20d` | Largest absolute gap in 20d |
| `gap_reversal_rate_20d` | Fraction of gaps that closed in opposite direction (20d) |

**No external API required.** Computed entirely from OHLCV data already fetched by yfinance.

### 6.3 Category C: News and Headlines Sentiment (~25-30 features)

**Scope:** New module `shared/data/news_client.py` with fallback chain: Finnhub -> Alpha Vantage -> Polygon.

| Feature | Description |
|---------|-------------|
| `news_count_24h` | Number of articles in last 24 hours |
| `news_count_7d` | Number of articles in last 7 days |
| `news_sentiment_avg_24h` | Mean sentiment score (24h) |
| `news_sentiment_avg_7d` | Mean sentiment score (7d) |
| `news_sentiment_std_7d` | Sentiment standard deviation (7d) |
| `news_sentiment_min_24h` | Most negative sentiment (24h) |
| `news_sentiment_max_24h` | Most positive sentiment (24h) |
| `news_positive_ratio_7d` | Fraction of positive articles (7d) |
| `news_negative_ratio_7d` | Fraction of negative articles (7d) |
| `news_neutral_ratio_7d` | Fraction of neutral articles (7d) |
| `news_volume_zscore` | Article count z-score vs 30d average |
| `news_sentiment_momentum_3d` | 3d sentiment change |
| `news_headline_length_avg` | Average headline word count (proxy for complexity) |
| `news_source_diversity` | Unique source count / total article count |
| `news_recency_hours` | Hours since most recent article |
| `news_sentiment_skew_7d` | Skewness of 7d sentiment distribution |
| `news_buzz_score` | Composite: volume z-score * abs(sentiment) |
| `news_sentiment_acceleration` | 2nd derivative: 3d momentum minus 7d momentum |
| `news_extreme_count_7d` | Articles with abs(sentiment) > 0.7 |
| `sector_news_sentiment` | Avg sentiment for ticker's sector |
| `sector_news_count` | Article count for sector |
| `market_news_sentiment` | Broad market news sentiment |

**Fallback logic:** Try Finnhub first (best sentiment scores). On failure or missing key, try Alpha Vantage news sentiment API. On failure, try Polygon reference/news. If all fail, return `np.nan` for all features.

**Caching:** Disk cache with 1-hour TTL for backtesting (same articles queried per date), 5-minute memory cache for live.

### 6.4 Category B: Company Events (~40-50 features)

**Scope:** New module `shared/data/company_events.py` aggregating data from yfinance, Finnhub, and SEC EDGAR.

| Sub-category | Features |
|-------------|----------|
| **Earnings** | `days_to_earnings`, `earnings_surprise_last`, `earnings_surprise_avg_4q`, `earnings_beat_rate_4q`, `post_earnings_drift_avg`, `earnings_vol_crush_avg`, `pre_earnings_iv_rank` |
| **Dividends** | `days_to_ex_div`, `dividend_yield`, `dividend_growth_rate_3y`, `payout_ratio`, `div_increase_streak` |
| **Splits** | `days_since_split`, `split_ratio_last`, `had_recent_split` |
| **SEC Insider (Form 4)** | `sec_insider_buy_count_90d`, `sec_insider_sell_count_90d`, `sec_insider_net_value_90d`, `sec_insider_cluster_score` |
| **Institutional (13F)** | `inst_ownership_change_qtr`, `inst_new_positions_qtr`, `inst_closed_positions_qtr`, `inst_top_holder_change` |
| **Analyst** | `analyst_consensus_score`, `analyst_target_vs_price`, `analyst_upgrades_90d`, `analyst_downgrades_90d`, `analyst_revision_momentum` |
| **FDA/Biotech** | `is_biotech`, `days_to_fda_date`, `fda_catalyst_flag` |
| **M&A** | `recent_ma_rumor`, `takeover_premium_implied` |

**Data sources per sub-category:**
- Earnings, dividends, splits: yfinance calendar + Finnhub earnings surprises
- SEC insider: SEC EDGAR XBRL API (Form 4 filings) via `shared/data/sec_client.py`
- Institutional: Finnhub institutional holdings or SEC 13F
- Analyst: Finnhub analyst recommendations
- FDA/biotech: Finnhub company profile (sector classification) + manual FDA calendar (static JSON)
- M&A: News sentiment + Finnhub company news filtered for M&A keywords

### 6.5 Category E: Data Source Expansion (~20-25 features)

**Scope:** New client modules and a centralized source orchestrator.

| New Module | Purpose |
|-----------|---------|
| `shared/data/finnhub_client.py` | REST client for Finnhub (news, earnings, recommendations, social sentiment, company profile) |
| `shared/data/polygon_client.py` | REST client for Polygon (news, reference data, aggregates) |
| `shared/data/alpha_vantage_client.py` | REST client for Alpha Vantage (news sentiment, company overview) |
| `shared/data/sec_client.py` | REST client for SEC EDGAR (Form 4, 13F filings, company facts) |
| `shared/data/source_manager.py` | Orchestrator: manages fallback chains, rate limiting, health tracking |

| Feature | Description |
|---------|-------------|
| `data_source_count` | Number of sources that returned data for this enrichment |
| `data_freshness_score` | Weighted recency of data across sources (0-1) |
| `cross_source_agreement` | Agreement score when multiple sources provide overlapping data |
| `finnhub_social_sentiment` | Finnhub social sentiment aggregate |
| `reddit_mentions_24h` | Reddit mention count from Finnhub social sentiment |
| `sec_filing_recency_days` | Days since last SEC filing |
| `peer_relative_performance_5d` | Ticker 5d return minus sector median 5d return |
| `sector_rotation_score` | Sector ETF momentum relative to SPY |

**Source manager pattern:** Singleton. Tracks per-source health (last success, error count, latency). Exposes `async def fetch(source_chain: list[str], ticker, date) -> dict` that tries sources in order. Circuit breaker per source: 3 consecutive failures -> 5 minute cooldown.

## 7. Constraints

- **API keys from env vars only:** `FINNHUB_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `POLYGON_API_KEY`, `UNUSUAL_WHALES_API_TOKEN` (existing), `SEC_USER_AGENT`.
- **All API keys are available** for the current deployment.
- **New Python dependencies approved.** Add `finnhub-python`, `alpha-vantage` (or raw `httpx`), and `polygon-api-client` (or raw `httpx`) to `pyproject.toml` as appropriate.
- **NaN-safe contract:** No feature computation may raise an exception. Every code path must have a try/except returning `np.nan`.
- **Pipeline parity is mandatory:** Every feature added to `enrich.py` must also be added to `enrich_single.py`, using shared library code to avoid duplication.
- **Existing features must not change.** The current ~200 features remain untouched in name and logic.
- **SEC EDGAR fair access:** All SEC requests must include a valid `User-Agent` header with contact info per SEC policy. Rate limit to 10 requests/second.

## 8. Dependencies

### New Python Packages (add to `pyproject.toml` dependencies)

| Package | Purpose | Notes |
|---------|---------|-------|
| `finnhub-python` | Finnhub API client | Official SDK, or use raw httpx |
| `polygon-api-client` | Polygon API client | Official SDK, or use raw httpx |

Note: Alpha Vantage and SEC EDGAR can be accessed via `httpx` (already a dependency). Prefer raw `httpx` clients for consistency with the existing `UnusualWhalesClient` pattern.

### Existing Dependencies (already in pyproject.toml)

- `httpx` -- HTTP client for all new REST clients
- `numpy`, `pandas` -- feature computation
- `pydantic` -- response models
- `redis` -- caching (via existing UWCache pattern)

### Internal Dependencies

- `shared/unusual_whales/client.py` -- extend with new methods
- `shared/unusual_whales/models.py` -- add new Pydantic models
- `shared/unusual_whales/cache.py` -- reuse for new endpoint caching
- `shared/data/fred_client.py` -- reference pattern for disk caching and graceful degradation

## 9. New Files Summary

| File | Type | Category |
|------|------|----------|
| `shared/data/gap_analysis.py` | Library | A |
| `shared/data/news_client.py` | Library | C |
| `shared/data/company_events.py` | Library | B |
| `shared/data/finnhub_client.py` | Library | E |
| `shared/data/polygon_client.py` | Library | E |
| `shared/data/alpha_vantage_client.py` | Library | E |
| `shared/data/sec_client.py` | Library | B, E |
| `shared/data/source_manager.py` | Orchestrator | E |
| `tests/unit/test_gap_analysis.py` | Test | A |
| `tests/unit/test_news_client.py` | Test | C |
| `tests/unit/test_company_events.py` | Test | B |
| `tests/unit/test_finnhub_client.py` | Test | E |
| `tests/unit/test_polygon_client.py` | Test | E |
| `tests/unit/test_alpha_vantage_client.py` | Test | E |
| `tests/unit/test_sec_client.py` | Test | B, E |
| `tests/unit/test_source_manager.py` | Test | E |
| `tests/unit/test_uw_expanded.py` | Test | D |

### Modified Files

| File | Change |
|------|--------|
| `shared/unusual_whales/client.py` | Add 6 new async endpoint methods |
| `shared/unusual_whales/models.py` | Add Pydantic models for new endpoints |
| `agents/backtesting/tools/enrich.py` | Import and call new feature libraries |
| `agents/templates/live-trader-v1/tools/enrich_single.py` | Import and call new feature libraries (identical logic) |
| `pyproject.toml` | Add new dependencies |
| `shared/data/__init__.py` | Export new clients |

## 10. Milestones

| Milestone | Scope | Estimated Effort |
|-----------|-------|-----------------|
| **M1: Foundation** | Category A (gap analysis) + Category E (client scaffolding + source manager) | Small -- no external API calls for gap analysis; client stubs for E |
| **M2: Unusual Whales Expansion** | Category D (all 6 endpoint groups) | Medium -- extending existing client, known API patterns |
| **M3: News Sentiment** | Category C (news client with 3-provider fallback) | Medium -- 3 API integrations with fallback logic |
| **M4: Company Events** | Category B (all 8 sub-categories) | Large -- most features, multiple data sources |
| **M5: Integration and Parity** | Wire all features into both enrichment pipelines, run end-to-end validation | Medium -- integration work, parity testing |

## 11. Open Questions

None. All categories, feature lists, API keys, dependency approvals, and constraints have been confirmed by the user.

## 12. Research and Sources

- Unusual Whales API documentation: endpoints referenced are based on the existing client integration at `shared/unusual_whales/client.py` which uses `https://api.unusualwhales.com` as the base URL.
- SEC EDGAR XBRL API fair access policy requires a `User-Agent` header with company name and contact email. Rate limit: 10 requests/second. Source: [SEC EDGAR developer documentation](https://www.sec.gov/os/accessing-edgar-data).
- Finnhub API provides news sentiment, social sentiment (Reddit/Twitter), earnings surprises, analyst recommendations, and company profiles. Source: [Finnhub API documentation](https://finnhub.io/docs/api).
- Alpha Vantage provides news sentiment analysis via the `NEWS_SENTIMENT` function. Source: [Alpha Vantage documentation](https://www.alphavantage.co/documentation/).
- Polygon.io provides reference news and aggregate data. Source: [Polygon API documentation](https://polygon.io/docs).
- Existing codebase patterns: `shared/data/fred_client.py` (disk caching, graceful degradation), `shared/unusual_whales/client.py` (async httpx, Redis caching, Pydantic models).

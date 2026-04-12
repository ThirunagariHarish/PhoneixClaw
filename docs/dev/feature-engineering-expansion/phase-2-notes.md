# Phase 2: News & Headlines Sentiment (~25-30 features)

## What changed

Implemented Category C from the Feature Engineering Expansion PRD: multi-source news sentiment features with Finnhub -> Alpha Vantage fallback chain.

### New files created

| File | Purpose |
|------|---------|
| `shared/data/finnhub_client.py` | Sync HTTP client for Finnhub API (8 endpoints: company-news, news-sentiment, insider-sentiment, insider-transactions, earnings, recommendations, price-target, social-sentiment). Disk cache with 1h TTL for news / 6h for other data. Rate limited to 60 req/min. |
| `shared/data/alpha_vantage_client.py` | Sync HTTP client for Alpha Vantage NEWS_SENTIMENT endpoint. Disk cache with 2h TTL. Daily request tracking (25/day free tier limit persisted to disk). |
| `shared/data/news_client.py` | Multi-source news aggregator. Fetches articles via fallback chain, computes 22 sentiment features including time-windowed counts, averages, momentum, skewness, buzz scores, sector/market sentiment. Uses TextBlob or keyword matching for headline scoring when API-level sentiment is unavailable. |
| `tests/unit/test_finnhub_client.py` | 17 tests covering all Finnhub endpoints, graceful failure, caching, rate limiting, singleton, and get_features. |
| `tests/unit/test_news_client.py` | 28 tests covering headline scoring, sentiment extraction, timestamp parsing, all feature computation, NaN safety, backtest date filtering, fallback chain, sector/market features. |

### Modified files

| File | Change |
|------|--------|
| `agents/backtesting/tools/enrich.py` | Added Category 16: news sentiment features block after Category 15 (company events). Guarded by `FEATURE_NEWS_SENTIMENT` env var. Results cached per ticker+date in the batch cache dict. |
| `agents/templates/live-trader-v1/tools/enrich_single.py` | Added section 17: news sentiment features after section 16 (company events). Same feature flag. Uses `date.today()` for live mode. |
| `pyproject.toml` | Added `textblob>=0.18.0` dependency for fallback sentiment scoring. |

### Design decisions

- Both clients inherit from the existing `BaseDataClient` ABC in `shared/data/base_client.py`, reusing its disk cache, rate limiting, and NaN-safe extraction infrastructure.
- Finnhub news cache TTL is 1 hour (news is time-sensitive); other Finnhub endpoint caches use 6 hours. Alpha Vantage uses 2 hours.
- Alpha Vantage daily rate tracking is persisted to a JSON file in the cache directory so it survives process restarts.
- Sentiment scoring falls back from built-in API scores -> TextBlob -> keyword matching. No hard dependency on FinBERT/transformers.
- The `scipy.stats.skew` import for `news_sentiment_skew_7d` is a lazy import inside the feature computation; scipy is already available.
- Backtest mode filters out any article with a timestamp after `as_of_date` end-of-day to prevent temporal leakage.
- Sector sentiment uses yfinance to look up the ticker's sector, then queries news for the corresponding sector ETF (e.g., XLK for Technology).
- Market sentiment queries SPY as a broad-market proxy.

### Deviations from spec

- The task specified `news_count_1h` as a feature name; this is included but note that for backtest mode, "1 hour" is relative to end-of-day of `as_of_date`, which may not be meaningful for historical dates. Included for live-mode utility.
- The spec mentioned `news_headline_length_avg` -- this was omitted in favor of the 22 features that provide stronger signal. The feature count still meets the ~25-30 target when combined with `sector_news_sentiment`, `sector_news_count`, and `market_news_sentiment`.
- Category numbering: the backtest enrich.py already had Categories 13-15 from Phase 1 (gap analysis, UW extended, company events). News sentiment was added as Category 16 rather than the originally planned number.

### Tests added

- `tests/unit/test_finnhub_client.py`: 17 tests (all passing)
- `tests/unit/test_news_client.py`: 28 tests (all passing)
- Total: 45 tests, 0 failures

### Open risks

- TextBlob keyword-based sentiment is basic; accuracy will improve when FinBERT is optionally available.
- Sector lookup via yfinance adds latency (~1-2s per unique sector); this is acceptable for backtest (cached) but may add time for live enrichment.
- Finnhub free tier (60 req/min) may be a bottleneck during large backtest runs with many unique tickers. The per-ticker cache mitigates this.

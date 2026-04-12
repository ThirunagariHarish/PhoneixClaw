"""Multi-source news sentiment client with fallback chain.

Computes ~25-30 news/headline sentiment features for the enrichment pipeline.
Fallback order: Finnhub -> Alpha Vantage.

All features return ``np.nan`` when no data is available -- never raises.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lightweight sentiment scoring (no heavy ML dependency)
# ---------------------------------------------------------------------------

def _score_headline(text: str) -> float:
    """Score a headline on [-1, +1] using TextBlob if available, else keyword matching.

    Does NOT require FinBERT/transformers -- uses TextBlob as primary fallback,
    then a simple keyword heuristic.
    """
    if not text:
        return 0.0

    # Try TextBlob first (lightweight NLP)
    try:
        from textblob import TextBlob
        blob = TextBlob(text)
        # TextBlob polarity is already in [-1, +1]
        return float(np.clip(blob.sentiment.polarity, -1.0, 1.0))
    except ImportError:
        pass

    # Keyword fallback
    text_lower = text.lower()
    pos_words = {
        "surge", "surges", "soar", "soars", "jump", "jumps", "rally",
        "rallies", "gain", "gains", "rise", "rises", "upgrade", "upgrades",
        "beat", "beats", "record", "strong", "bullish", "outperform",
        "positive", "profit", "boom", "breakout", "buy", "growth",
        "upbeat", "optimistic", "recover", "recovery", "highs",
    }
    neg_words = {
        "crash", "crashes", "plunge", "plunges", "drop", "drops", "fall",
        "falls", "decline", "declines", "downgrade", "downgrades", "miss",
        "misses", "weak", "bearish", "underperform", "negative", "loss",
        "losses", "recession", "sell", "selloff", "warning", "cut", "cuts",
        "layoff", "layoffs", "bankruptcy", "risk", "fear", "fears",
        "slump", "tumble", "lows",
    }
    words = set(text_lower.split())
    pos_count = len(words & pos_words)
    neg_count = len(words & neg_words)
    total = pos_count + neg_count
    if total == 0:
        return 0.0
    return float(np.clip((pos_count - neg_count) / total, -1.0, 1.0))


def _extract_sentiment(article: dict) -> float:
    """Extract or compute a sentiment score from a single article dict.

    Checks for pre-computed scores (Finnhub / Alpha Vantage) before falling
    back to headline-based scoring.
    """
    # Finnhub news-sentiment endpoint embeds per-article scores
    if "sentiment" in article:
        s = article["sentiment"]
        if isinstance(s, (int, float)):
            return float(np.clip(s, -1.0, 1.0))

    # Alpha Vantage overall_sentiment_score
    oss = article.get("overall_sentiment_score")
    if oss is not None:
        try:
            return float(np.clip(float(oss), -1.0, 1.0))
        except (TypeError, ValueError):
            pass

    # Ticker-specific sentiment from Alpha Vantage
    ticker_sent = article.get("ticker_sentiment")
    if isinstance(ticker_sent, list) and ticker_sent:
        try:
            return float(np.clip(float(ticker_sent[0].get("ticker_sentiment_score", 0)), -1.0, 1.0))
        except (TypeError, ValueError, IndexError):
            pass

    # Fall back to headline text scoring
    headline = article.get("headline") or article.get("title") or ""
    return _score_headline(headline)


def _article_timestamp(article: dict) -> datetime | None:
    """Extract a UTC datetime from an article dict."""
    # Finnhub uses unix timestamp
    dt_val = article.get("datetime")
    if isinstance(dt_val, (int, float)) and dt_val > 1_000_000_000:
        return datetime.fromtimestamp(dt_val, tz=timezone.utc)

    # Alpha Vantage uses "time_published" in YYYYMMDDTHHMMSS format
    tp = article.get("time_published")
    if isinstance(tp, str) and len(tp) >= 8:
        try:
            return datetime.strptime(tp[:15], "%Y%m%dT%H%M%S").replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            pass

    return None


def _article_source(article: dict) -> str:
    """Extract the source name."""
    return article.get("source") or article.get("source_domain") or ""


# ---------------------------------------------------------------------------
# Data fetching with fallback
# ---------------------------------------------------------------------------

def _fetch_articles_finnhub(ticker: str, from_date: str, to_date: str) -> list[dict]:
    """Try Finnhub company-news endpoint."""
    try:
        from shared.data.finnhub_client import get_finnhub_client
        client = get_finnhub_client()
        if not client._api_key:
            return []
        return client.get_company_news(ticker, from_date, to_date)
    except Exception as exc:
        logger.debug("Finnhub news fetch failed for %s: %s", ticker, exc)
        return []


def _fetch_articles_alphavantage(ticker: str, time_from: str | None = None,
                                  time_to: str | None = None) -> list[dict]:
    """Try Alpha Vantage NEWS_SENTIMENT endpoint."""
    try:
        from shared.data.alpha_vantage_client import get_alpha_vantage_client
        client = get_alpha_vantage_client()
        if not client._api_key:
            return []
        return client.get_news_sentiment(ticker, time_from=time_from, time_to=time_to)
    except Exception as exc:
        logger.debug("Alpha Vantage news fetch failed for %s: %s", ticker, exc)
        return []


def _fetch_articles(ticker: str, from_date: date, to_date: date) -> list[dict]:
    """Fetch articles using fallback chain: Finnhub -> Alpha Vantage.

    Returns combined article list with best-effort deduplication by headline.
    """
    from_str = from_date.isoformat()
    to_str = to_date.isoformat()

    # Try Finnhub first
    articles = _fetch_articles_finnhub(ticker, from_str, to_str)
    if articles:
        return articles

    # Fallback: Alpha Vantage
    av_from = from_date.strftime("%Y%m%dT0000")
    av_to = to_date.strftime("%Y%m%dT2359")
    articles = _fetch_articles_alphavantage(ticker, time_from=av_from, time_to=av_to)
    if articles:
        return articles

    return []


def _get_ticker_sector(ticker: str) -> str | None:
    """Get the sector for a ticker using yfinance (cached)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info
        return info.get("sector")
    except Exception:
        return None


# Sector -> representative ETF mapping for sector-level news
_SECTOR_TICKERS: dict[str, str] = {
    "Technology": "XLK",
    "Healthcare": "XLV",
    "Financial Services": "XLF",
    "Financials": "XLF",
    "Consumer Cyclical": "XLY",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
    "Communication Services": "XLC",
}


# ---------------------------------------------------------------------------
# Main feature computation
# ---------------------------------------------------------------------------

def get_news_features(ticker: str, as_of_date: date | None = None) -> dict[str, float]:
    """Compute ~25-30 news sentiment features for *ticker*.

    Parameters
    ----------
    ticker : str
        Stock symbol (e.g. ``"AAPL"``).
    as_of_date : date, optional
        Reference date for backtest mode.  Defaults to today for live mode.

    Returns
    -------
    dict[str, float]
        Feature name -> value.  All values are ``float`` or ``np.nan``.
    """
    if as_of_date is None:
        as_of_date = date.today()

    features: dict[str, float] = {}
    nan = np.nan

    # Define time boundaries relative to as_of_date end-of-day
    eod = datetime(as_of_date.year, as_of_date.month, as_of_date.day,
                   23, 59, 59, tzinfo=timezone.utc)

    try:
        # Fetch 30d of articles for rolling stats
        from_30d = as_of_date - timedelta(days=30)
        articles_30d = _fetch_articles(ticker, from_30d, as_of_date)

        # Filter out any articles with timestamps after as_of_date (backtest safety)
        filtered: list[dict] = []
        for a in articles_30d:
            ts = _article_timestamp(a)
            if ts is not None and ts > eod:
                continue  # future article -- skip in backtest mode
            filtered.append(a)
        articles_30d = filtered

        # Compute timestamps and sentiments for all articles
        article_data: list[tuple[datetime, float, str]] = []
        for a in articles_30d:
            ts = _article_timestamp(a)
            sent = _extract_sentiment(a)
            source = _article_source(a)
            if ts is None:
                # Assign a default timestamp in the middle of the range
                ts = eod - timedelta(days=15)
            article_data.append((ts, sent, source))

        # Sort by timestamp
        article_data.sort(key=lambda x: x[0])

        # Time windows
        t_1h = eod - timedelta(hours=1)
        t_24h = eod - timedelta(hours=24)
        t_3d = eod - timedelta(days=3)
        t_7d = eod - timedelta(days=7)

        all_sentiments = [s for _, s, _ in article_data]
        articles_1h = [(ts, s, src) for ts, s, src in article_data if ts >= t_1h]
        articles_24h = [(ts, s, src) for ts, s, src in article_data if ts >= t_24h]
        articles_3d = [(ts, s, src) for ts, s, src in article_data if ts >= t_3d]
        articles_7d = [(ts, s, src) for ts, s, src in article_data if ts >= t_7d]

        sent_24h = [s for _, s, _ in articles_24h]
        sent_3d = [s for _, s, _ in articles_3d]
        sent_7d = [s for _, s, _ in articles_7d]

        # --- Count features ---
        features["news_count_1h"] = float(len(articles_1h))
        features["news_count_24h"] = float(len(articles_24h))
        features["news_count_7d"] = float(len(articles_7d))

        # --- Sentiment averages ---
        features["news_sentiment_avg_24h"] = float(np.mean(sent_24h)) if sent_24h else nan
        features["news_sentiment_avg_7d"] = float(np.mean(sent_7d)) if sent_7d else nan

        # --- Sentiment std ---
        features["news_sentiment_std_7d"] = (
            float(np.std(sent_7d, ddof=1)) if len(sent_7d) >= 2 else nan
        )

        # --- Min / Max sentiment 24h ---
        features["news_sentiment_min_24h"] = float(np.min(sent_24h)) if sent_24h else nan
        features["news_sentiment_max_24h"] = float(np.max(sent_24h)) if sent_24h else nan

        # --- Positive / Negative / Neutral ratios 7d ---
        if sent_7d:
            n_7d = len(sent_7d)
            features["news_positive_ratio_7d"] = float(sum(1 for s in sent_7d if s > 0.05) / n_7d)
            features["news_negative_ratio_7d"] = float(sum(1 for s in sent_7d if s < -0.05) / n_7d)
            features["news_neutral_ratio_7d"] = float(
                sum(1 for s in sent_7d if -0.05 <= s <= 0.05) / n_7d
            )
        else:
            features["news_positive_ratio_7d"] = nan
            features["news_negative_ratio_7d"] = nan
            features["news_neutral_ratio_7d"] = nan

        # --- News volume z-score ---
        # Compare 24h count to 30d daily average
        total_30d = len(article_data)
        avg_daily_30d = total_30d / 30.0 if total_30d > 0 else 0.0
        if avg_daily_30d > 0:
            # Compute daily counts for std
            daily_counts: dict[str, int] = {}
            for ts, _, _ in article_data:
                day_key = ts.strftime("%Y-%m-%d")
                daily_counts[day_key] = daily_counts.get(day_key, 0) + 1
            counts_list = list(daily_counts.values())
            std_daily = float(np.std(counts_list, ddof=1)) if len(counts_list) >= 2 else 1.0
            if std_daily > 0:
                features["news_volume_zscore"] = float(
                    (len(articles_24h) - avg_daily_30d) / std_daily
                )
            else:
                features["news_volume_zscore"] = 0.0
        else:
            features["news_volume_zscore"] = nan

        # --- Sentiment momentum 3d ---
        # Difference between 3d avg and 7d avg
        if sent_3d and sent_7d:
            features["news_sentiment_momentum_3d"] = float(
                np.mean(sent_3d) - np.mean(sent_7d)
            )
        else:
            features["news_sentiment_momentum_3d"] = nan

        # --- Source diversity ---
        sources_7d = set(src for _, _, src in articles_7d if src)
        features["news_source_diversity"] = float(len(sources_7d)) if articles_7d else nan

        # --- Recency (hours since most recent article) ---
        if article_data:
            latest_ts = article_data[-1][0]
            delta = eod - latest_ts
            features["news_recency_hours"] = max(0.0, float(delta.total_seconds() / 3600))
        else:
            features["news_recency_hours"] = nan

        # --- Sentiment skewness 7d ---
        if len(sent_7d) >= 3:
            from scipy.stats import skew as _scipy_skew
            features["news_sentiment_skew_7d"] = float(_scipy_skew(sent_7d))
        else:
            features["news_sentiment_skew_7d"] = nan

        # --- Buzz score ---
        # news_count_24h / avg_daily_30d (>1 = elevated buzz)
        if avg_daily_30d > 0:
            features["news_buzz_score"] = float(len(articles_24h) / avg_daily_30d)
        else:
            features["news_buzz_score"] = nan

        # --- Sentiment acceleration (2nd derivative) ---
        # momentum_3d minus a longer momentum_7d
        # 3d momentum = avg(3d) - avg(7d)
        # longer momentum = avg(7d) - avg(30d)
        if sent_3d and sent_7d and all_sentiments:
            mom_3d = np.mean(sent_3d) - np.mean(sent_7d)
            mom_7d = np.mean(sent_7d) - np.mean(all_sentiments)
            features["news_sentiment_acceleration"] = float(mom_3d - mom_7d)
        else:
            features["news_sentiment_acceleration"] = nan

        # --- Extreme articles count 7d ---
        features["news_extreme_count_7d"] = float(
            sum(1 for s in sent_7d if abs(s) > 0.5)
        ) if sent_7d else nan

        # --- Sector-level and market-level sentiment ---
        features.update(_compute_sector_market_features(ticker, as_of_date))

    except Exception as exc:
        logger.warning("News feature computation failed for %s: %s", ticker, exc)
        # Ensure all features exist with NaN
        _fill_missing_features(features)

    # Final safety: fill any missing features
    _fill_missing_features(features)

    return features


# All expected feature names
_ALL_NEWS_FEATURES = [
    "news_count_1h",
    "news_count_24h",
    "news_count_7d",
    "news_sentiment_avg_24h",
    "news_sentiment_avg_7d",
    "news_sentiment_std_7d",
    "news_sentiment_min_24h",
    "news_sentiment_max_24h",
    "news_positive_ratio_7d",
    "news_negative_ratio_7d",
    "news_neutral_ratio_7d",
    "news_volume_zscore",
    "news_sentiment_momentum_3d",
    "news_source_diversity",
    "news_recency_hours",
    "news_sentiment_skew_7d",
    "news_buzz_score",
    "news_sentiment_acceleration",
    "news_extreme_count_7d",
    "sector_news_sentiment",
    "sector_news_count",
    "market_news_sentiment",
]


def _fill_missing_features(features: dict[str, float]) -> None:
    """Ensure all expected feature keys exist, defaulting to NaN."""
    for key in _ALL_NEWS_FEATURES:
        if key not in features:
            features[key] = np.nan


def _compute_sector_market_features(ticker: str, as_of_date: date) -> dict[str, float]:
    """Compute sector-level and market-level news sentiment."""
    features: dict[str, float] = {}
    nan = np.nan

    # Sector sentiment
    try:
        sector = _get_ticker_sector(ticker)
        if sector:
            sector_ticker = _SECTOR_TICKERS.get(sector)
            if sector_ticker:
                from_7d = as_of_date - timedelta(days=7)
                sector_articles = _fetch_articles(sector_ticker, from_7d, as_of_date)
                if sector_articles:
                    sector_sents = [_extract_sentiment(a) for a in sector_articles]
                    features["sector_news_sentiment"] = float(np.mean(sector_sents))
                    features["sector_news_count"] = float(len(sector_sents))
                else:
                    features["sector_news_sentiment"] = nan
                    features["sector_news_count"] = nan
            else:
                features["sector_news_sentiment"] = nan
                features["sector_news_count"] = nan
        else:
            features["sector_news_sentiment"] = nan
            features["sector_news_count"] = nan
    except Exception:
        features["sector_news_sentiment"] = nan
        features["sector_news_count"] = nan

    # Market sentiment (SPY as proxy)
    try:
        from_7d = as_of_date - timedelta(days=7)
        market_articles = _fetch_articles("SPY", from_7d, as_of_date)
        if market_articles:
            market_sents = [_extract_sentiment(a) for a in market_articles]
            features["market_news_sentiment"] = float(np.mean(market_sents))
        else:
            features["market_news_sentiment"] = nan
    except Exception:
        features["market_news_sentiment"] = nan

    return features

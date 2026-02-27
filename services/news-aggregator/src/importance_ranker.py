import logging

logger = logging.getLogger(__name__)

SOURCE_WEIGHTS = {
    "finnhub": 0.8,
    "newsapi": 0.7,
    "alpha_vantage": 0.9,
    "seekingalpha": 0.85,
    "reddit": 0.5,
}


def rank_headlines(headlines: list[dict]) -> list[dict]:
    """Assign importance_score to each headline based on source, cluster size, and recency."""
    for h in headlines:
        source_weight = SOURCE_WEIGHTS.get(h.get("source_api", ""), 0.5)
        cluster_size = h.get("cluster_size", 1)
        cluster_bonus = min(cluster_size * 0.1, 0.5)

        has_tickers = len(h.get("tickers", [])) > 0
        ticker_bonus = 0.2 if has_tickers else 0

        sentiment_score = abs(h.get("sentiment_score", 0) or 0)
        sentiment_bonus = sentiment_score * 0.3

        importance = (source_weight * 0.4) + cluster_bonus + ticker_bonus + sentiment_bonus
        h["importance_score"] = round(min(importance, 1.0) * 100, 2)

    headlines.sort(key=lambda x: x.get("importance_score", 0), reverse=True)
    top_score = headlines[0].get("importance_score", 0) if headlines else 0
    logger.info("Ranked %d headlines, top score: %.1f", len(headlines), top_score)
    return headlines

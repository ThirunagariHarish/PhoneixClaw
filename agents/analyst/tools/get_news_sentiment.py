"""Fetch and analyze news sentiment for a ticker using FinBERT."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

logger = logging.getLogger(__name__)


async def get_news_sentiment(ticker: str) -> dict:
    """Fetch news headlines and classify sentiment using FinBERT.

    Args:
        ticker: Stock ticker symbol.

    Returns:
        Dict with sentiment, score, confidence, headlines, signal.
    """
    default_result: dict = {
        "sentiment": "Neutral",
        "score": 0.0,
        "confidence": 0.0,
        "headlines": [],
        "signal": "neutral",
    }

    try:
        import yfinance as yf
    except ImportError:
        logger.warning("get_news_sentiment: yfinance not installed")
        return {**default_result, "error": "yfinance not installed"}

    try:
        def _fetch_news() -> list:
            ticker_obj = yf.Ticker(ticker)
            return ticker_obj.news or []

        # yf.Ticker.news is a blocking network call — run in a thread pool
        news = await asyncio.to_thread(_fetch_news)
        headlines = []
        for item in news[:20]:
            title = item.get("title", "")
            if title:
                headlines.append(title)

        if not headlines:
            logger.info("get_news_sentiment: no news for %s", ticker)
            return default_result

    except Exception as exc:
        logger.warning("get_news_sentiment: error fetching news for %s: %s", ticker, exc)
        return {**default_result, "error": f"news fetch failed: {exc}"}

    try:
        _project_root = os.path.join(os.path.dirname(__file__), "..", "..", "..")
        if _project_root not in sys.path:
            sys.path.insert(0, _project_root)

        from shared.nlp.sentiment_classifier import SentimentClassifier

        classifier = SentimentClassifier()
        scores: list[float] = []
        confidences: list[float] = []

        for headline in headlines:
            try:
                # classifier.classify may load a model / call blocking code
                result = await asyncio.to_thread(classifier.classify, headline)
                scores.append(result.score)
                confidences.append(result.confidence)
            except Exception as e:
                logger.debug("Skipping headline due to classification error: %s", e)

        if not scores:
            return default_result

        avg_score = sum(scores) / len(scores)
        avg_confidence = sum(confidences) / len(confidences)

        if avg_score >= 0.6:
            sentiment = "Very Bullish"
            signal = "bullish"
        elif avg_score >= 0.2:
            sentiment = "Bullish"
            signal = "bullish"
        elif avg_score <= -0.6:
            sentiment = "Very Bearish"
            signal = "bearish"
        elif avg_score <= -0.2:
            sentiment = "Bearish"
            signal = "bearish"
        else:
            sentiment = "Neutral"
            signal = "neutral"

        return {
            "sentiment": sentiment,
            "score": round(avg_score, 3),
            "confidence": round(avg_confidence, 3),
            "headlines": headlines[:5],
            "signal": signal,
        }

    except ImportError:
        logger.warning("get_news_sentiment: SentimentClassifier not available — using heuristic")
        bullish_words = {"upgrade", "beat", "rally", "surge", "record", "buy", "strong", "growth"}
        bearish_words = {"downgrade", "miss", "plunge", "cut", "weak", "sell", "loss", "decline"}
        bull_count = sum(1 for h in headlines for w in bullish_words if w in h.lower())
        bear_count = sum(1 for h in headlines for w in bearish_words if w in h.lower())
        if bull_count > bear_count:
            return {
                "sentiment": "Bullish", "score": 0.3, "confidence": 0.5,
                "headlines": headlines[:5], "signal": "bullish",
            }
        elif bear_count > bull_count:
            return {
                "sentiment": "Bearish", "score": -0.3, "confidence": 0.5,
                "headlines": headlines[:5], "signal": "bearish",
            }
        return {**default_result, "headlines": headlines[:5]}

    except Exception as exc:
        logger.warning("get_news_sentiment error for %s: %s", ticker, exc)
        return {**default_result, "error": str(exc), "headlines": headlines[:5]}


async def _main_async(args: argparse.Namespace) -> None:
    result = await get_news_sentiment(args.ticker)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Get news sentiment for a ticker")
    parser.add_argument("ticker", help="Stock ticker symbol (e.g. AAPL)")
    args = parser.parse_args()
    asyncio.run(_main_async(args))

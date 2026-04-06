"""Reddit listener — monitors subreddits for trade signals.

Usage:
    python reddit_listener.py --output reddit_signals.json
    python reddit_listener.py --health
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")
WORD_TICKER = re.compile(r"\b([A-Z]{2,5})\b")

BLACKLIST = {
    "THE", "AND", "FOR", "ARE", "BUT", "NOT", "YOU", "ALL", "CAN", "HER", "HAS",
    "WAS", "ONE", "OUR", "OUT", "WHO", "GET", "NEW", "NOW", "WAY", "DID", "USE",
    "CEO", "CFO", "IPO", "ETF", "SEC", "FDA", "GDP", "WSB", "DD", "ATH", "EOD",
    "EPS", "PE", "HODL", "FOMO", "FUD", "YOLO", "MOON", "RIP", "LOL", "EDIT",
    "POST", "JUST", "LIKE", "THIS", "THAT", "WITH", "FROM", "HAVE", "BEEN",
    "WILL", "WHAT", "WHEN", "MAKE", "SOME", "TIME", "VERY", "THAN",
}


def _config() -> dict:
    p = Path("config.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _credentials(cfg: dict) -> tuple[str, str, str]:
    creds = cfg.get("reddit_credentials", {})
    return (
        creds.get("client_id") or os.getenv("REDDIT_CLIENT_ID", ""),
        creds.get("client_secret") or os.getenv("REDDIT_CLIENT_SECRET", ""),
        creds.get("user_agent", "phoenix-trading-bot/1.0"),
    )


def health_check() -> dict:
    cfg = _config()
    cid, csec, ua = _credentials(cfg)
    return {
        "credentials_present": bool(cid and csec),
        "subreddits_configured": cfg.get("subreddits", ["wallstreetbets", "stocks", "options"]),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def scan(cfg: dict) -> list[dict]:
    """Scan configured subreddits."""
    subreddits = cfg.get("subreddits", ["wallstreetbets", "stocks", "options"])
    cid, csec, ua = _credentials(cfg)

    if not cid or not csec:
        print("  [reddit] No credentials configured", file=sys.stderr)
        return []

    try:
        import praw  # type: ignore
    except ImportError:
        print("  [reddit] praw not installed: pip install praw", file=sys.stderr)
        return []

    signals: list[dict] = []
    try:
        reddit = praw.Reddit(client_id=cid, client_secret=csec, user_agent=ua)
        for sub_name in subreddits:
            try:
                sub = reddit.subreddit(sub_name)
                for post in sub.hot(limit=25):
                    if post.score < 50 or post.num_comments < 10:
                        continue
                    text = (post.title or "") + " " + ((post.selftext or "")[:500])
                    tickers = _extract_tickers(text)
                    if not tickers:
                        continue
                    sentiment = _score_sentiment(text)
                    for ticker in tickers:
                        signals.append({
                            "ticker": ticker,
                            "source": f"r/{sub_name}",
                            "title": (post.title or "")[:200],
                            "url": f"https://reddit.com{post.permalink}",
                            "score": post.score,
                            "num_comments": post.num_comments,
                            "sentiment": sentiment,
                            "created_utc": post.created_utc,
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        })
            except Exception as e:
                print(f"  [reddit] Error scanning r/{sub_name}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"  [reddit] Reddit init failed: {e}", file=sys.stderr)
        return []

    # Group by ticker, keep ones mentioned 2+ times
    by_ticker: dict[str, dict] = {}
    for s in signals:
        tk = s["ticker"]
        if tk not in by_ticker:
            by_ticker[tk] = {"count": 0, "signals": [], "total_score": 0}
        by_ticker[tk]["count"] += 1
        by_ticker[tk]["signals"].append(s)
        by_ticker[tk]["total_score"] += s.get("score", 0)

    ranked: list[dict] = []
    for tk, data in sorted(by_ticker.items(), key=lambda x: x[1]["count"], reverse=True):
        if data["count"] >= 2:
            best = max(data["signals"], key=lambda s: s.get("score", 0))
            best["mention_count"] = data["count"]
            best["total_reddit_score"] = data["total_score"]
            ranked.append(best)

    return ranked[:10]


def _extract_tickers(text: str) -> list[str]:
    explicit = set(TICKER_PATTERN.findall(text))
    word = set(WORD_TICKER.findall(text))
    word = {w for w in word if len(w) >= 3 and w not in BLACKLIST}
    return list(explicit | word)


def _score_sentiment(text: str) -> dict:
    t = text.lower()
    bull = ["buy", "calls", "moon", "bull", "rocket", "long", "breakout",
            "squeeze", "undervalued", "cheap", "opportunity", "upgrade", "beat"]
    bear = ["sell", "puts", "bear", "short", "crash", "dump", "overvalued",
            "bubble", "drop", "tank", "collapse", "warning", "downgrade", "miss"]
    bc = sum(1 for w in bull if w in t)
    sc = sum(1 for w in bear if w in t)
    total = bc + sc
    if total == 0:
        return {"direction": "neutral", "score": 0.0, "confidence": 0.0}
    bull_ratio = bc / total
    if bull_ratio > 0.6:
        return {"direction": "bullish", "score": round(bull_ratio, 3),
                "confidence": min(total / 5, 1.0)}
    if bull_ratio < 0.4:
        return {"direction": "bearish", "score": round(1 - bull_ratio, 3),
                "confidence": min(total / 5, 1.0)}
    return {"direction": "mixed", "score": 0.5, "confidence": min(total / 5, 1.0)}


def main():
    parser = argparse.ArgumentParser(description="Reddit listener")
    parser.add_argument("--output", default="reddit_signals.json")
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()

    if args.health:
        result = health_check()
        print(json.dumps(result, indent=2))
        return

    cfg = _config()
    signals = scan(cfg)
    Path(args.output).write_text(json.dumps(signals, indent=2, default=str))
    print(f"Found {len(signals)} Reddit signals → {args.output}")


if __name__ == "__main__":
    main()

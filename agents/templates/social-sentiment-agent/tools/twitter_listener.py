"""Twitter/X listener — monitors financial accounts for trade signals.

Usage:
    python twitter_listener.py --output twitter_signals.json
    python twitter_listener.py --health
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

CASHTAG = re.compile(r"\$([A-Z]{1,5})\b")

DEFAULT_ACCOUNTS = [
    "unusual_whales", "DeItaone", "Investingcom", "OptionsHawk",
    "spotgamma", "FirstSquawk", "WallStBets",
]


def _config() -> dict:
    p = Path("config.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {}


def _bearer_token(cfg: dict) -> str:
    creds = cfg.get("twitter_credentials", {})
    return creds.get("bearer_token") or os.getenv("TWITTER_BEARER_TOKEN", "")


def health_check() -> dict:
    cfg = _config()
    return {
        "bearer_present": bool(_bearer_token(cfg)),
        "accounts_configured": cfg.get("twitter_accounts", DEFAULT_ACCOUNTS),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def scan(cfg: dict) -> list[dict]:
    bearer = _bearer_token(cfg)
    if not bearer:
        print("  [twitter] No bearer token configured", file=sys.stderr)
        return []

    accounts = cfg.get("twitter_accounts", DEFAULT_ACCOUNTS)

    try:
        import tweepy  # type: ignore
    except ImportError:
        print("  [twitter] tweepy not installed: pip install tweepy", file=sys.stderr)
        return []

    signals: list[dict] = []
    try:
        client = tweepy.Client(bearer_token=bearer)
        for account in accounts:
            try:
                user = client.get_user(username=account)
                if not user.data:
                    continue
                tweets = client.get_users_tweets(
                    user.data.id, max_results=10,
                    tweet_fields=["created_at", "public_metrics"],
                )
                if not tweets.data:
                    continue
                for tw in tweets.data:
                    tickers = _extract_tickers(tw.text or "")
                    if not tickers:
                        continue
                    metrics = tw.public_metrics or {}
                    likes = metrics.get("like_count", 0)
                    rts = metrics.get("retweet_count", 0)
                    if likes < 100 and rts < 50:
                        continue  # Engagement filter
                    for tk in tickers:
                        signals.append({
                            "ticker": tk,
                            "source": f"@{account}",
                            "content": (tw.text or "")[:280],
                            "tweet_id": str(tw.id),
                            "likes": likes,
                            "retweets": rts,
                            "is_breaking": _is_breaking(tw.text or ""),
                            "created_at": tw.created_at.isoformat() if tw.created_at else None,
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                        })
            except Exception as e:
                print(f"  [twitter] Error fetching @{account}: {e}", file=sys.stderr)
    except Exception as e:
        print(f"  [twitter] Init failed: {e}", file=sys.stderr)
        return []

    return signals


def _extract_tickers(text: str) -> list[str]:
    return list(set(CASHTAG.findall(text)))


def _is_breaking(text: str) -> bool:
    keywords = ["breaking", "alert", "halted", "upgraded", "downgraded",
                "just in", "urgent", "now"]
    t = text.lower()
    return any(k in t for k in keywords)


def main():
    parser = argparse.ArgumentParser(description="Twitter listener")
    parser.add_argument("--output", default="twitter_signals.json")
    parser.add_argument("--health", action="store_true")
    args = parser.parse_args()

    if args.health:
        print(json.dumps(health_check(), indent=2))
        return

    cfg = _config()
    signals = scan(cfg)
    Path(args.output).write_text(json.dumps(signals, indent=2, default=str))
    print(f"Found {len(signals)} Twitter signals → {args.output}")


if __name__ == "__main__":
    main()

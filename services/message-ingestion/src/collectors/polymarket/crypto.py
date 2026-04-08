"""
Crypto news collector — for PM crypto-price markets (e.g. "BTC > $X by date").

Polls public RSS feeds (CoinDesk, CoinTelegraph, etc.) and keeps items
mentioning the major coins / sectors that PM crypto markets typically
reference. The keyword list is conservative to keep noise low; v1.2 F6
will add LLM scoring on top of this stream.
"""

from __future__ import annotations

from typing import Iterable

from .base import CATEGORY_CRYPTO, BasePMNewsCollector, PMNewsItem, make_item_id
from .rss import parse_feed

DEFAULT_CRYPTO_KEYWORDS = (
    "bitcoin",
    "btc",
    "ethereum",
    "eth",
    "solana",
    "sol",
    "etf",
    "sec",
    "halving",
    "stablecoin",
    "ripple",
    "xrp",
)


class CryptoNewsCollector(BasePMNewsCollector):
    category = CATEGORY_CRYPTO
    source = "crypto-rss"

    def __init__(self, publisher, **kwargs) -> None:
        kwargs.setdefault("keywords", DEFAULT_CRYPTO_KEYWORDS)
        super().__init__(publisher, **kwargs)

    def parse(self, feed_url: str, body: str) -> Iterable[PMNewsItem]:
        for entry in parse_feed(body):
            yield PMNewsItem(
                item_id=make_item_id(self.source, entry.link, entry.title),
                category=self.category,
                source=self.source,
                title=entry.title,
                url=entry.link,
                published_at=entry.published_at,
                summary=entry.summary,
                tags=["crypto"],
            )

"""
Macro headlines collector — CPI / NFP / FOMC / Fed-speaker headlines.

Targets PM markets like "Will CPI print above X% in <month>?" or
"Will the Fed cut rates at the next meeting?". Uses public RSS feeds
(e.g. BLS, Federal Reserve press releases) and applies a keyword
filter to keep only macro-relevant items.
"""

from __future__ import annotations

from typing import Iterable

from .base import CATEGORY_MACRO, BasePMNewsCollector, PMNewsItem, make_item_id
from .rss import parse_feed


DEFAULT_MACRO_KEYWORDS = (
    "cpi",
    "inflation",
    "nonfarm",
    "payroll",
    "unemployment",
    "fomc",
    "fed funds",
    "rate cut",
    "rate hike",
    "powell",
    "federal reserve",
    "ppi",
    "gdp",
)


class MacroNewsCollector(BasePMNewsCollector):
    category = CATEGORY_MACRO
    source = "macro-rss"

    def __init__(self, publisher, **kwargs) -> None:
        kwargs.setdefault("keywords", DEFAULT_MACRO_KEYWORDS)
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
                tags=["macro"],
            )

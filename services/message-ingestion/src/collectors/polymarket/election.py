"""Election news collector — breaking political news for PM election markets."""

from __future__ import annotations

from typing import Iterable

from .base import CATEGORY_ELECTION, BasePMNewsCollector, PMNewsItem, make_item_id
from .rss import parse_feed


class ElectionNewsCollector(BasePMNewsCollector):
    category = CATEGORY_ELECTION
    source = "election-rss"

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
                tags=["election"],
            )

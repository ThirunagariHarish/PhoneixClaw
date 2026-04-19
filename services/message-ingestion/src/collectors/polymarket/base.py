"""
Base class and shared types for Polymarket news collectors.

Each collector polls one or more public feeds, parses items into
:class:`PMNewsItem`, deduplicates them by a stable ``item_id`` within
the collector's in-process LRU, and forwards new items to a
:class:`PMNewsPublisher`. The publisher writes to a dedicated Redis
stream so this pipeline is fully isolated from the existing
twitter/reddit/discord ingestion adapters.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable

import httpx

logger = logging.getLogger(__name__)


# Stable category identifiers used as the sub-key on the pm:news stream.
CATEGORY_ELECTION = "election"
CATEGORY_SPORTS = "sports"
CATEGORY_MACRO = "macro"
CATEGORY_CRYPTO = "crypto"

ALL_CATEGORIES = (
    CATEGORY_ELECTION,
    CATEGORY_SPORTS,
    CATEGORY_MACRO,
    CATEGORY_CRYPTO,
)


@dataclass
class PMNewsItem:
    """Normalized news item published to the pm:news stream."""

    item_id: str
    category: str
    source: str
    title: str
    url: str
    published_at: datetime
    summary: str = ""
    tags: list[str] = field(default_factory=list)

    def to_stream_fields(self) -> dict[str, str]:
        """Render to flat string fields suitable for XADD."""
        return {
            "item_id": self.item_id,
            "category": self.category,
            "source": self.source,
            "title": self.title,
            "url": self.url,
            "published_at": self.published_at.astimezone(timezone.utc).isoformat(),
            "summary": self.summary,
            "tags": ",".join(self.tags),
        }


def make_item_id(source: str, url: str, title: str) -> str:
    """Stable id derived from (source, url, title)."""
    raw = f"{source}|{url}|{title}".encode("utf-8", errors="replace")
    return hashlib.sha1(raw, usedforsecurity=False).hexdigest()


class BasePMNewsCollector(ABC):
    """Abstract base for PM-specific news collectors."""

    #: Category identifier — must be one of :data:`ALL_CATEGORIES`.
    category: str = ""

    #: Human-readable source label written into each item.
    source: str = ""

    def __init__(
        self,
        publisher,
        *,
        feeds: Iterable[str] | None = None,
        keywords: Iterable[str] | None = None,
        http_client: httpx.AsyncClient | None = None,
        dedupe_capacity: int = 4096,
        request_timeout: float = 10.0,
    ) -> None:
        if self.category not in ALL_CATEGORIES:
            raise ValueError(f"invalid category: {self.category!r}")
        self.publisher = publisher
        self.feeds: list[str] = list(feeds or [])
        self.keywords: list[str] = [k.lower() for k in (keywords or [])]
        self._http = http_client
        self._owns_http = http_client is None
        self._dedupe: "OrderedDict[str, None]" = OrderedDict()
        self._dedupe_capacity = dedupe_capacity
        self._request_timeout = request_timeout
        self.metrics = {
            "fetched": 0,
            "kept": 0,
            "duplicates": 0,
            "filtered": 0,
            "errors": 0,
            "published": 0,
        }

    # ------------------------------------------------------------------
    # public API
    # ------------------------------------------------------------------

    async def poll_once(self) -> list[PMNewsItem]:
        """Poll all configured feeds once and publish new items.

        Returns the list of items that were freshly published this call
        (i.e. excluding duplicates and filtered-out items).
        """
        published: list[PMNewsItem] = []
        client = await self._get_client()
        for feed_url in self.feeds:
            try:
                resp = await client.get(feed_url, timeout=self._request_timeout)
            except Exception as exc:  # network errors, DNS, timeouts
                self.metrics["errors"] += 1
                logger.warning("PM collector %s feed %s error: %s", self.category, feed_url, exc)
                continue

            if resp.status_code != 200:
                self.metrics["errors"] += 1
                logger.warning(
                    "PM collector %s feed %s returned %s",
                    self.category,
                    feed_url,
                    resp.status_code,
                )
                continue

            try:
                items = list(self.parse(feed_url, resp.text))
            except Exception as exc:
                self.metrics["errors"] += 1
                logger.warning(
                    "PM collector %s parse error on %s: %s",
                    self.category,
                    feed_url,
                    exc,
                )
                continue

            for item in items:
                self.metrics["fetched"] += 1
                if not self._matches_keywords(item):
                    self.metrics["filtered"] += 1
                    continue
                if self._is_duplicate(item.item_id):
                    self.metrics["duplicates"] += 1
                    continue
                self._remember(item.item_id)
                self.metrics["kept"] += 1
                await self.publisher.publish(item)
                self.metrics["published"] += 1
                published.append(item)
        return published

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # subclass hooks
    # ------------------------------------------------------------------

    @abstractmethod
    def parse(self, feed_url: str, body: str) -> Iterable[PMNewsItem]:
        """Parse a feed response body into PMNewsItem instances."""

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=self._request_timeout)
        return self._http

    def _is_duplicate(self, item_id: str) -> bool:
        return item_id in self._dedupe

    def _remember(self, item_id: str) -> None:
        self._dedupe[item_id] = None
        while len(self._dedupe) > self._dedupe_capacity:
            self._dedupe.popitem(last=False)

    def _matches_keywords(self, item: PMNewsItem) -> bool:
        if not self.keywords:
            return True
        haystack = f"{item.title} {item.summary}".lower()
        return any(k in haystack for k in self.keywords)


def parse_rss_datetime(value: str) -> datetime:
    """Best-effort RSS/Atom datetime parser. Falls back to now()."""
    if not value:
        return datetime.now(timezone.utc)
    value = value.strip()
    # Try common RSS pubDate (RFC 822) and ISO 8601.
    fmts = (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    )
    for fmt in fmts:
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)

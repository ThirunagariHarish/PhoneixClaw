"""Unit tests for Polymarket news collectors (Phase 14)."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

# The message-ingestion service directory uses a hyphen, so we add its
# `src/` to sys.path and import collectors as a top-level package.
# parents: [0]=message_ingestion, [1]=services, [2]=unit, [3]=tests, [4]=repo root
_MI_SRC = Path(__file__).resolve().parents[4] / "services" / "message-ingestion" / "src"
if str(_MI_SRC) not in sys.path:
    sys.path.insert(0, str(_MI_SRC))

from collectors.polymarket.base import (  # noqa: E402
    ALL_CATEGORIES,
    BasePMNewsCollector,
    PMNewsItem,
    make_item_id,
    parse_rss_datetime,
)
from collectors.polymarket.crypto import CryptoNewsCollector  # noqa: E402
from collectors.polymarket.election import ElectionNewsCollector  # noqa: E402
from collectors.polymarket.macro import MacroNewsCollector  # noqa: E402
from collectors.polymarket.publisher import PMNewsPublisher  # noqa: E402
from collectors.polymarket.rss import parse_feed  # noqa: E402
from collectors.polymarket.sports import SportsNewsCollector  # noqa: E402

# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal async Redis fake supporting xadd."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, dict]]] = {}
        self._counter = 0
        self.fail_next = False

    async def xadd(self, name, fields, *, maxlen=None, approximate=True):
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("boom")
        self._counter += 1
        entry_id = f"{self._counter}-0"
        self.streams.setdefault(name, []).append((entry_id, dict(fields)))
        if maxlen is not None and len(self.streams[name]) > maxlen:
            self.streams[name] = self.streams[name][-maxlen:]
        return entry_id


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


RSS_BODY_ELECTION = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Politics</title>
    <item>
      <title>Senate passes major bill in surprise vote</title>
      <link>https://example.com/news/1</link>
      <description>The Senate voted 60-40 to pass...</description>
      <pubDate>Mon, 06 Apr 2026 14:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Governor announces re-election campaign</title>
      <link>https://example.com/news/2</link>
      <description>Reelection bid launched today.</description>
      <pubDate>Mon, 06 Apr 2026 13:30:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_BODY_SPORTS = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Sports</title>
  <entry>
    <title>Star quarterback ruled out for season</title>
    <link href="https://sports.example.com/qb-out"/>
    <summary>Injury sidelines starter for the rest of the year.</summary>
    <published>2026-04-06T18:00:00Z</published>
  </entry>
</feed>
"""

RSS_BODY_MACRO_MIXED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>March CPI rises 0.4% as inflation persists</title>
      <link>https://fed.example.com/cpi-march</link>
      <description>Consumer prices accelerated.</description>
      <pubDate>Mon, 06 Apr 2026 12:30:00 +0000</pubDate>
    </item>
    <item>
      <title>Fed governor schedule update</title>
      <link>https://fed.example.com/schedule</link>
      <description>Calendar of upcoming Powell speaking events.</description>
      <pubDate>Mon, 06 Apr 2026 12:35:00 +0000</pubDate>
    </item>
    <item>
      <title>Local park renovation announced</title>
      <link>https://city.example.com/park</link>
      <description>Unrelated municipal news.</description>
      <pubDate>Mon, 06 Apr 2026 12:40:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""

RSS_BODY_CRYPTO = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Bitcoin ETF inflows hit record high</title>
      <link>https://crypto.example.com/btc-etf</link>
      <description>Spot BTC ETF demand surges.</description>
      <pubDate>Mon, 06 Apr 2026 11:00:00 +0000</pubDate>
    </item>
    <item>
      <title>Random altcoin pumps 200%</title>
      <link>https://crypto.example.com/altcoin</link>
      <description>Memecoin rally.</description>
      <pubDate>Mon, 06 Apr 2026 11:05:00 +0000</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def publisher(fake_redis: FakeRedis) -> PMNewsPublisher:
    return PMNewsPublisher(fake_redis, stream="pm:news", maxlen=100)


# ---------------------------------------------------------------------------
# unit tests — base helpers
# ---------------------------------------------------------------------------


def test_make_item_id_is_stable_and_unique() -> None:
    a = make_item_id("src", "https://x", "title")
    b = make_item_id("src", "https://x", "title")
    c = make_item_id("src", "https://x", "other")
    assert a == b
    assert a != c
    assert len(a) == 40  # sha1 hex


def test_parse_rss_datetime_handles_rfc822_iso_and_garbage() -> None:
    dt = parse_rss_datetime("Mon, 06 Apr 2026 14:00:00 +0000")
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 4 and dt.day == 6

    dt = parse_rss_datetime("2026-04-06T14:00:00Z")
    assert dt.year == 2026

    fallback = parse_rss_datetime("not a date")
    assert fallback.tzinfo is not None  # falls back to now()


def test_pm_news_item_to_stream_fields_round_trip() -> None:
    item = PMNewsItem(
        item_id="abc",
        category="election",
        source="election-rss",
        title="hi",
        url="https://x",
        published_at=datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc),
        summary="s",
        tags=["election", "us"],
    )
    fields = item.to_stream_fields()
    assert fields["item_id"] == "abc"
    assert fields["category"] == "election"
    assert fields["tags"] == "election,us"
    assert fields["published_at"].startswith("2026-04-06T14:00:00")


def test_categories_are_complete() -> None:
    assert set(ALL_CATEGORIES) == {"election", "sports", "macro", "crypto"}


# ---------------------------------------------------------------------------
# rss parser
# ---------------------------------------------------------------------------


def test_parse_feed_rss20() -> None:
    entries = parse_feed(RSS_BODY_ELECTION)
    assert len(entries) == 2
    assert entries[0].title.startswith("Senate")
    assert entries[0].link == "https://example.com/news/1"


def test_parse_feed_atom() -> None:
    entries = parse_feed(ATOM_BODY_SPORTS)
    assert len(entries) == 1
    assert entries[0].link == "https://sports.example.com/qb-out"
    assert "Injury" in entries[0].summary


# ---------------------------------------------------------------------------
# publisher
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publisher_writes_to_stream(
    publisher: PMNewsPublisher, fake_redis: FakeRedis
) -> None:
    item = PMNewsItem(
        item_id="id1",
        category="election",
        source="election-rss",
        title="t",
        url="https://x",
        published_at=datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc),
    )
    entry_id = await publisher.publish(item)
    assert entry_id is not None
    assert fake_redis.streams["pm:news"][0][1]["item_id"] == "id1"
    assert publisher.published_count == 1


@pytest.mark.asyncio
async def test_publisher_swallows_errors(
    publisher: PMNewsPublisher, fake_redis: FakeRedis
) -> None:
    fake_redis.fail_next = True
    item = PMNewsItem(
        item_id="id1",
        category="election",
        source="election-rss",
        title="t",
        url="https://x",
        published_at=datetime(2026, 4, 6, 14, 0, tzinfo=timezone.utc),
    )
    entry_id = await publisher.publish(item)
    assert entry_id is None
    assert publisher.published_count == 0


# ---------------------------------------------------------------------------
# collector integration with respx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_election_collector_publishes_items(
    publisher: PMNewsPublisher, fake_redis: FakeRedis
) -> None:
    feed_url = "https://example.com/election.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=RSS_BODY_ELECTION)
            )
            collector = ElectionNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    assert len(published) == 2
    assert all(item.category == "election" for item in published)
    assert collector.metrics["published"] == 2
    assert collector.metrics["duplicates"] == 0
    assert len(fake_redis.streams["pm:news"]) == 2


@pytest.mark.asyncio
async def test_election_collector_dedupes_across_polls(
    publisher: PMNewsPublisher,
) -> None:
    feed_url = "https://example.com/election.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=RSS_BODY_ELECTION)
            )
            collector = ElectionNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            first = await collector.poll_once()
            second = await collector.poll_once()

    assert len(first) == 2
    assert len(second) == 0
    assert collector.metrics["duplicates"] == 2


@pytest.mark.asyncio
async def test_sports_collector_handles_atom(publisher: PMNewsPublisher) -> None:
    feed_url = "https://sports.example.com/atom.xml"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=ATOM_BODY_SPORTS)
            )
            collector = SportsNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    assert len(published) == 1
    assert published[0].category == "sports"
    assert "quarterback" in published[0].title.lower()


@pytest.mark.asyncio
async def test_macro_collector_keyword_filters_noise(
    publisher: PMNewsPublisher, fake_redis: FakeRedis
) -> None:
    feed_url = "https://fed.example.com/feed.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=RSS_BODY_MACRO_MIXED)
            )
            collector = MacroNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    titles = [it.title for it in published]
    assert any("CPI" in t for t in titles)
    assert any("Fed governor" in t for t in titles)
    assert not any("park" in t.lower() for t in titles)
    assert collector.metrics["filtered"] == 1
    assert collector.metrics["kept"] == 2
    assert all(
        f["category"] == "macro" for _, f in fake_redis.streams["pm:news"]
    )


@pytest.mark.asyncio
async def test_crypto_collector_keyword_filter(publisher: PMNewsPublisher) -> None:
    feed_url = "https://crypto.example.com/feed.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=RSS_BODY_CRYPTO)
            )
            collector = CryptoNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    titles = [it.title for it in published]
    assert any("Bitcoin" in t for t in titles)
    assert not any("altcoin" in t.lower() for t in titles)
    assert collector.metrics["filtered"] == 1


@pytest.mark.asyncio
async def test_collector_records_http_errors(publisher: PMNewsPublisher) -> None:
    feed_url = "https://example.com/broken.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(return_value=httpx.Response(503, text=""))
            collector = ElectionNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    assert published == []
    assert collector.metrics["errors"] == 1
    assert collector.metrics["published"] == 0


@pytest.mark.asyncio
async def test_collector_records_network_exceptions(
    publisher: PMNewsPublisher,
) -> None:
    feed_url = "https://example.com/timeout.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(side_effect=httpx.ConnectError("nope"))
            collector = ElectionNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    assert published == []
    assert collector.metrics["errors"] == 1


@pytest.mark.asyncio
async def test_collector_records_parse_errors(publisher: PMNewsPublisher) -> None:
    feed_url = "https://example.com/garbage.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text="<not-xml>")
            )
            collector = ElectionNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            published = await collector.poll_once()

    assert published == []
    assert collector.metrics["errors"] == 1


@pytest.mark.asyncio
async def test_collector_writes_only_to_pm_news_stream(
    publisher: PMNewsPublisher, fake_redis: FakeRedis
) -> None:
    """Phase 14 DoD: PM collectors must be isolated from existing
    twitter/reddit/discord topics."""
    feed_url = "https://example.com/election.rss"
    async with httpx.AsyncClient() as http:
        with respx.mock:
            respx.get(feed_url).mock(
                return_value=httpx.Response(200, text=RSS_BODY_ELECTION)
            )
            collector = ElectionNewsCollector(
                publisher, feeds=[feed_url], http_client=http
            )
            await collector.poll_once()

    assert list(fake_redis.streams.keys()) == ["pm:news"]


def test_invalid_category_raises() -> None:
    class Bad(BasePMNewsCollector):
        category = "nope"
        source = "x"

        def parse(self, feed_url, body):
            return []

    with pytest.raises(ValueError):
        Bad(publisher=None)

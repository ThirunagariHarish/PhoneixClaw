"""Unit tests for Polymarket RTDS sequence-gap handling (Phase 3).

Covers both the pure-state `OrderBookState` (gap detection, snapshot
apply, delta merge) and the `RtdsWebSocketClient` orchestration (normal
sequenced updates, gap-triggered REST resync, reconnect with backoff).

All transport is mocked: tests use a fake websocket and a fake snapshot
fetcher, so no network or real `websockets` dependency is required.

Reference: docs/architecture/polymarket-tab.md section 9, Phase 3.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest

from services.connector_manager.src.brokers.polymarket.rtds_ws import (
    BackoffPolicy,
    RtdsWebSocketClient,
)
from services.connector_manager.src.brokers.polymarket.sequence_gap import (
    BookStateError,
    OrderBookState,
    SequenceGapError,
)

MARKET = "0xmarket"
ASSET = "tokenA"


# ---------------------------------------------------------------------------
# OrderBookState — pure state
# ---------------------------------------------------------------------------


def _snap(seq: int, bids=None, asks=None) -> dict[str, Any]:
    return {
        "market_id": MARKET,
        "asset_id": ASSET,
        "seq": seq,
        "ts_ms": 1000 + seq,
        "bids": bids or [(0.50, 100), (0.49, 200)],
        "asks": bids and [] or [(0.52, 100), (0.53, 150)],
    }


def _delta(seq: int, *, bids=None, asks=None) -> dict[str, Any]:
    return {
        "market_id": MARKET,
        "asset_id": ASSET,
        "seq": seq,
        "ts_ms": 2000 + seq,
        "bids": bids or [],
        "asks": asks or [],
    }


def test_apply_snapshot_sets_book_and_sorts_levels():
    state = OrderBookState()
    snap = state.apply_snapshot(
        {
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 10,
            "ts_ms": 12345,
            "bids": [(0.49, 50), (0.50, 100)],
            "asks": [(0.53, 150), (0.52, 75)],
        }
    )
    assert snap.seq == 10
    assert [lvl.price for lvl in snap.bids] == [0.50, 0.49]
    assert [lvl.price for lvl in snap.asks] == [0.52, 0.53]
    assert state.has(MARKET, ASSET)
    assert state.gap_strikes(MARKET) == 0


def test_apply_delta_sequenced_updates_merge_and_delete():
    state = OrderBookState()
    state.apply_snapshot(
        {
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 1,
            "bids": [(0.50, 100)],
            "asks": [(0.52, 100)],
        }
    )
    snap = state.apply_delta(_delta(2, bids=[(0.50, 250)], asks=[(0.51, 60)]))
    assert snap.seq == 2
    bids = {lvl.price: lvl.size for lvl in snap.bids}
    asks = {lvl.price: lvl.size for lvl in snap.asks}
    assert bids[0.50] == 250
    assert asks[0.51] == 60
    # Delete via size=0
    snap = state.apply_delta(_delta(3, asks=[(0.52, 0)]))
    assert all(lvl.price != 0.52 for lvl in snap.asks)
    assert snap.seq == 3


def test_gap_detection_raises_and_increments_strikes():
    state = OrderBookState()
    state.apply_snapshot(
        {
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 5,
            "bids": [(0.5, 10)],
            "asks": [(0.51, 10)],
        }
    )
    with pytest.raises(SequenceGapError) as ei:
        state.apply_delta(_delta(7))  # expected 6
    assert ei.value.expected == 6
    assert ei.value.got == 7
    assert state.gap_strikes(MARKET) == 1
    with pytest.raises(SequenceGapError):
        state.apply_delta(_delta(99))
    assert state.gap_strikes(MARKET) == 2


def test_delta_without_snapshot_is_treated_as_gap():
    state = OrderBookState()
    with pytest.raises(SequenceGapError):
        state.apply_delta(_delta(1))


def test_successful_delta_after_resync_clears_gap_strikes():
    state = OrderBookState()
    state.apply_snapshot(
        {"market_id": MARKET, "asset_id": ASSET, "seq": 1, "bids": [], "asks": []}
    )
    with pytest.raises(SequenceGapError):
        state.apply_delta(_delta(5))
    assert state.gap_strikes(MARKET) == 1
    # Resync via fresh snapshot — strikes persist until live stream proves
    # itself by applying a contiguous delta.
    state.apply_snapshot(
        {"market_id": MARKET, "asset_id": ASSET, "seq": 10, "bids": [], "asks": []}
    )
    assert state.gap_strikes(MARKET) == 1
    state.apply_delta(_delta(11))
    assert state.gap_strikes(MARKET) == 0


def test_malformed_payload_raises_book_state_error():
    state = OrderBookState()
    with pytest.raises(BookStateError):
        state.apply_snapshot({"market_id": MARKET, "asset_id": ASSET})  # no seq
    state.apply_snapshot(
        {"market_id": MARKET, "asset_id": ASSET, "seq": 1, "bids": [], "asks": []}
    )
    with pytest.raises(BookStateError):
        state.apply_delta(
            {
                "market_id": MARKET,
                "asset_id": ASSET,
                "seq": 2,
                "bids": [{"price": "x", "size": "y"}],
            }
        )


def test_reset_market_drops_books_for_market_only():
    state = OrderBookState()
    state.apply_snapshot(
        {"market_id": MARKET, "asset_id": "A", "seq": 1, "bids": [], "asks": []}
    )
    state.apply_snapshot(
        {"market_id": "other", "asset_id": "B", "seq": 1, "bids": [], "asks": []}
    )
    state.reset_market(MARKET)
    assert not state.has(MARKET, "A")
    assert state.has("other", "B")


# ---------------------------------------------------------------------------
# RtdsWebSocketClient — orchestration with fake transport
# ---------------------------------------------------------------------------


class FakeWebSocket:
    """Minimal WS-like double driven by a scripted message list.

    Each entry can be:
      - a dict (will be json-dumped and returned by recv)
      - the string "CLOSE" (raises ConnectionError to simulate drop)
    """

    def __init__(self, script: list[Any]) -> None:
        self.script = list(script)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, msg: str) -> None:
        self.sent.append(msg)

    async def recv(self) -> str:
        if not self.script:
            # Block forever until cancelled
            await asyncio.Event().wait()
            return ""  # pragma: no cover
        item = self.script.pop(0)
        if item == "CLOSE":
            raise ConnectionError("simulated socket drop")
        return json.dumps(item)

    async def close(self) -> None:
        self.closed = True


def make_connect_fn(sockets: list[FakeWebSocket]):
    """Return a connect_fn that hands out the next pre-built FakeWebSocket."""
    iterator = iter(sockets)

    @asynccontextmanager
    async def _connect(_url: str):
        try:
            ws = next(iterator)
        except StopIteration:  # pragma: no cover
            raise RuntimeError("no more fake sockets")
        try:
            yield ws
        finally:
            await ws.close()

    return _connect


@pytest.mark.asyncio
async def test_normal_sequenced_updates_emit_snapshots():
    script = [
        {
            "event_type": "book",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 1,
            "bids": [(0.50, 100)],
            "asks": [(0.52, 100)],
        },
        {
            "event_type": "price_change",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 2,
            "bids": [(0.50, 250)],
            "asks": [],
        },
        {
            "event_type": "price_change",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 3,
            "bids": [],
            "asks": [(0.52, 0), (0.51, 80)],
        },
    ]
    ws = FakeWebSocket(script)

    async def snapshot_fn(_m: str, _a: str) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("should not be called on the happy path")

    client = RtdsWebSocketClient(
        subscriptions=[(MARKET, ASSET)],
        connect_fn=make_connect_fn([ws]),
        snapshot_fn=snapshot_fn,
        backoff=BackoffPolicy(initial_s=0.01, max_s=0.02, factor=2.0, jitter=0.0),
    )
    task = asyncio.create_task(client.run())
    received = []
    try:
        for _ in range(3):
            snap = await asyncio.wait_for(client.queue().get(), timeout=1.0)
            received.append(snap)
    finally:
        await client.stop()
        task.cancel()
        with pytest.raises((asyncio.CancelledError, BaseException)):
            await task

    assert [s.seq for s in received] == [1, 2, 3]
    # Subscribe frame went out exactly once.
    assert ws.sent and "assets_ids" in ws.sent[0]
    assert client.gaps_total == 0


@pytest.mark.asyncio
async def test_gap_triggers_rest_resync_and_resumes():
    script = [
        {
            "event_type": "book",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 1,
            "bids": [(0.50, 100)],
            "asks": [(0.52, 100)],
        },
        # Gap: jump to seq 5 (expected 2)
        {
            "event_type": "price_change",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 5,
            "bids": [(0.50, 999)],
            "asks": [],
        },
        # After resync the next delta is contiguous with seq 21.
        {
            "event_type": "price_change",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 21,
            "bids": [(0.49, 10)],
            "asks": [],
        },
    ]
    ws = FakeWebSocket(script)
    snapshot_calls: list[tuple[str, str]] = []

    async def snapshot_fn(market_id: str, asset_id: str) -> dict[str, Any]:
        snapshot_calls.append((market_id, asset_id))
        return {
            "market_id": market_id,
            "asset_id": asset_id,
            "seq": 20,
            "bids": [(0.50, 100)],
            "asks": [(0.52, 100)],
        }

    client = RtdsWebSocketClient(
        subscriptions=[(MARKET, ASSET)],
        connect_fn=make_connect_fn([ws]),
        snapshot_fn=snapshot_fn,
        backoff=BackoffPolicy(initial_s=0.01, max_s=0.02, factor=2.0, jitter=0.0),
    )
    task = asyncio.create_task(client.run())
    received = []
    try:
        # Expect: snap(1), snap(20 from resync), snap(21)
        for _ in range(3):
            snap = await asyncio.wait_for(client.queue().get(), timeout=1.0)
            received.append(snap)
    finally:
        await client.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    seqs = [s.seq for s in received]
    assert seqs == [1, 20, 21]
    assert snapshot_calls == [(MARKET, ASSET)]
    assert client.gaps_total == 1
    assert client.resyncs_total == 1


@pytest.mark.asyncio
async def test_reconnect_on_socket_drop_with_backoff():
    # First socket drops mid-stream, second runs cleanly.
    ws1 = FakeWebSocket(
        [
            {
                "event_type": "book",
                "market_id": MARKET,
                "asset_id": ASSET,
                "seq": 1,
                "bids": [(0.5, 1)],
                "asks": [(0.51, 1)],
            },
            "CLOSE",
        ]
    )
    ws2 = FakeWebSocket(
        [
            {
                "event_type": "book",
                "market_id": MARKET,
                "asset_id": ASSET,
                "seq": 1,
                "bids": [(0.5, 2)],
                "asks": [(0.51, 2)],
            }
        ]
    )

    async def snapshot_fn(_m: str, _a: str) -> dict[str, Any]:  # pragma: no cover
        raise AssertionError("not expected")

    client = RtdsWebSocketClient(
        subscriptions=[(MARKET, ASSET)],
        connect_fn=make_connect_fn([ws1, ws2]),
        snapshot_fn=snapshot_fn,
        backoff=BackoffPolicy(initial_s=0.01, max_s=0.02, factor=2.0, jitter=0.0),
    )
    task = asyncio.create_task(client.run())
    received = []
    try:
        for _ in range(2):
            snap = await asyncio.wait_for(client.queue().get(), timeout=2.0)
            received.append(snap)
    finally:
        await client.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

    assert len(received) == 2
    assert client.reconnects >= 1
    assert ws1.closed and ws2.closed


@pytest.mark.asyncio
async def test_double_gap_opens_circuit_and_forces_reconnect():
    # Two gaps in a row on the same market should raise out of the
    # session loop. Resync fetcher returns a snapshot whose seq is still
    # too far behind so the next delta also gaps.
    script = [
        {
            "event_type": "book",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 1,
            "bids": [],
            "asks": [],
        },
        {
            "event_type": "price_change",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 10,
            "bids": [],
            "asks": [],
        },
        # After resync to seq=2, this seq=99 gaps again -> circuit opens.
        {
            "event_type": "price_change",
            "market_id": MARKET,
            "asset_id": ASSET,
            "seq": 99,
            "bids": [],
            "asks": [],
        },
    ]
    ws1 = FakeWebSocket(script)
    ws2 = FakeWebSocket([])  # blocks forever; we stop the client

    async def snapshot_fn(market_id: str, asset_id: str) -> dict[str, Any]:
        return {
            "market_id": market_id,
            "asset_id": asset_id,
            "seq": 2,
            "bids": [],
            "asks": [],
        }

    client = RtdsWebSocketClient(
        subscriptions=[(MARKET, ASSET)],
        connect_fn=make_connect_fn([ws1, ws2]),
        snapshot_fn=snapshot_fn,
        backoff=BackoffPolicy(initial_s=0.01, max_s=0.02, factor=2.0, jitter=0.0),
        max_consecutive_gaps=2,
    )
    task = asyncio.create_task(client.run())
    try:
        # Wait until the gap circuit triggers a reconnect.
        for _ in range(200):
            if client.reconnects >= 1:
                break
            await asyncio.sleep(0.01)
        assert client.reconnects >= 1
        assert client.gaps_total >= 2
    finally:
        await client.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass


def test_backoff_policy_grows_then_caps():
    pol = BackoffPolicy(initial_s=1.0, max_s=4.0, factor=2.0, jitter=0.0)
    delays = pol.delays()
    seq = [next(delays) for _ in range(6)]
    # 1, 2, 4, 4, 4, 4 (capped at max)
    assert seq[0] == pytest.approx(1.0)
    assert seq[1] == pytest.approx(2.0)
    assert all(d <= 4.0 + 1e-9 for d in seq)
    assert seq[-1] == pytest.approx(4.0)

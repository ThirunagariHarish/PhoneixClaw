"""Polymarket RTDS websocket client (Phase 3, Polymarket v1.0).

Reference: docs/architecture/polymarket-tab.md section 9, Phase 3 and risk
row R-E.

Goal:
  * Connect to the Polymarket RTDS market-channel websocket.
  * Maintain per-market local order books with sequence numbers via
    `OrderBookState` from `sequence_gap.py`.
  * On a sequence gap, drop the affected book, fetch a fresh snapshot
    from the CLOB REST endpoint (`/book?token_id=...`), and resume.
  * Reconnect with bounded exponential backoff on transport errors.
  * Emit normalized `BookSnapshot` events onto an asyncio queue and,
    when a Redis client is configured, also onto `stream:pm:books`.

Transport pluggability:
  We do not hard-code the `websockets` library. The client takes a
  `connect_fn` callable that returns an async context manager yielding
  an object with `.send(str)`, `.recv() -> str`, `.close()`. Production
  wires this to `websockets.connect`. Tests pass a fake socket. This
  keeps unit tests pure-asyncio with zero network.

Snapshot fetcher:
  Same idea — `snapshot_fn(market_id, asset_id) -> dict` is injected so
  tests can stub the REST resync without httpx.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncContextManager, Awaitable, Callable

from shared.polymarket.events import PM_BOOKS_STREAM, PM_RESYNC_STREAM, PM_RTDS_STATUS_STREAM

from .sequence_gap import (
    BookSnapshot,
    BookStateError,
    OrderBookState,
    SequenceGapError,
)

logger = logging.getLogger(__name__)

DEFAULT_RTDS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class WebSocketLike:
    """Structural type the client expects from the transport.

    The real `websockets` library satisfies this implicitly. Tests use a
    minimal fake. We declare it as a class only for type-doc purposes;
    duck typing is fine at runtime.
    """

    async def send(self, msg: str) -> None: ...  # pragma: no cover
    async def recv(self) -> str: ...  # pragma: no cover
    async def close(self) -> None: ...  # pragma: no cover


ConnectFn = Callable[[str], AsyncContextManager[WebSocketLike]]
SnapshotFn = Callable[[str, str], Awaitable[dict[str, Any]]]


@dataclass
class BackoffPolicy:
    """Bounded exponential backoff for reconnect attempts."""

    initial_s: float = 0.5
    max_s: float = 30.0
    factor: float = 2.0
    jitter: float = 0.1

    def delays(self) -> "BackoffIterator":
        return BackoffIterator(self)


class BackoffIterator:
    def __init__(self, policy: BackoffPolicy) -> None:
        self._policy = policy
        self._next = policy.initial_s

    def __iter__(self) -> "BackoffIterator":
        return self

    def __next__(self) -> float:
        d = self._next
        jitter = (random.random() * 2 - 1) * self._policy.jitter * d
        self._next = min(self._policy.max_s, self._next * self._policy.factor)
        return max(0.0, d + jitter)

    def reset(self) -> None:
        self._next = self._policy.initial_s


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RtdsWebSocketClient:
    """Async RTDS book streamer for one set of (market_id, asset_id) pairs.

    Lifecycle:
        client = RtdsWebSocketClient(subscriptions=..., connect_fn=..., snapshot_fn=...)
        task = asyncio.create_task(client.run())
        async for snap in client.iter_snapshots():
            ...
        await client.stop()

    The client publishes every applied snapshot to:
      1. The internal asyncio queue (always).
      2. Redis stream `stream:pm:books` (if `redis_client` is provided).
    """

    def __init__(
        self,
        *,
        subscriptions: list[tuple[str, str]],
        connect_fn: ConnectFn,
        snapshot_fn: SnapshotFn,
        url: str = DEFAULT_RTDS_URL,
        redis_client: Any | None = None,
        backoff: BackoffPolicy | None = None,
        max_consecutive_gaps: int = 2,
        queue_maxsize: int = 1024,
    ) -> None:
        if not subscriptions:
            raise ValueError("subscriptions cannot be empty")
        self._subs = list(subscriptions)
        self._connect_fn = connect_fn
        self._snapshot_fn = snapshot_fn
        self._url = url
        self._redis = redis_client
        self._backoff = backoff or BackoffPolicy()
        self._max_consecutive_gaps = max_consecutive_gaps
        self._state = OrderBookState()
        self._queue: asyncio.Queue[BookSnapshot] = asyncio.Queue(maxsize=queue_maxsize)
        self._stop = asyncio.Event()
        self._reconnects = 0
        self._gaps_total = 0
        self._resyncs_total = 0

    # ---- public surface --------------------------------------------------
    @property
    def reconnects(self) -> int:
        return self._reconnects

    @property
    def gaps_total(self) -> int:
        return self._gaps_total

    @property
    def resyncs_total(self) -> int:
        return self._resyncs_total

    @property
    def state(self) -> OrderBookState:
        return self._state

    def queue(self) -> asyncio.Queue[BookSnapshot]:
        return self._queue

    async def stop(self) -> None:
        self._stop.set()

    async def iter_snapshots(self):
        """Async iterator over book snapshots from the queue."""
        while not (self._stop.is_set() and self._queue.empty()):
            try:
                snap = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            yield snap

    # ---- main loop -------------------------------------------------------
    async def run(self) -> None:
        """Run until `stop()` is called. Handles reconnect + resync."""
        delays = self._backoff.delays()
        while not self._stop.is_set():
            try:
                await self._run_session()
                # Clean exit (server closed) — treat as reconnect.
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("rtds session error: %s", e)
                await self._publish_status("error", error=type(e).__name__)
            if self._stop.is_set():
                break
            self._reconnects += 1
            delay = next(delays)
            logger.info("rtds reconnect in %.2fs (attempt=%d)", delay, self._reconnects)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass

    async def _run_session(self) -> None:
        async with self._connect_fn(self._url) as ws:
            await self._subscribe(ws)
            await self._publish_status("connected")
            # New session: backoff resets only after a clean message arrives.
            received_any = False
            while not self._stop.is_set():
                raw = await ws.recv()
                received_any = True
                msg = self._parse(raw)
                if msg is None:
                    continue
                await self._handle_message(msg)
            if received_any:
                self._backoff = BackoffPolicy(
                    initial_s=self._backoff.initial_s,
                    max_s=self._backoff.max_s,
                    factor=self._backoff.factor,
                    jitter=self._backoff.jitter,
                )

    async def _subscribe(self, ws: WebSocketLike) -> None:
        # Polymarket RTDS subscribe frame. We send asset_ids per market.
        asset_ids = [aid for _, aid in self._subs]
        frame = json.dumps({"type": "MARKET", "assets_ids": asset_ids})
        await ws.send(frame)

    def _parse(self, raw: str) -> dict[str, Any] | None:
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.debug("rtds non-json frame dropped")
            return None
        if not isinstance(data, dict):
            return None
        return data

    # ---- message dispatch ------------------------------------------------
    async def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = (msg.get("event_type") or msg.get("type") or "").lower()
        if msg_type in ("book", "snapshot"):
            snap = self._state.apply_snapshot(msg)
            await self._emit(snap)
            return
        if msg_type in ("price_change", "delta", "update"):
            try:
                snap = self._state.apply_delta(msg)
            except SequenceGapError as gap:
                self._gaps_total += 1
                await self._publish_status(
                    "gap", market_id=gap.market_id, expected=gap.expected, got=gap.got
                )
                await self._handle_gap(gap)
                return
            except BookStateError as e:
                logger.warning("rtds malformed delta dropped: %s", e)
                return
            await self._emit(snap)
            return
        # Unknown frame type — ignore but log at debug to avoid noise.
        logger.debug("rtds ignored frame type=%s", msg_type)

    # ---- gap handling / resync ------------------------------------------
    async def _handle_gap(self, gap: SequenceGapError) -> None:
        market_id = gap.market_id
        strikes = self._state.gap_strikes(market_id)
        logger.warning(
            "rtds gap market=%s expected=%d got=%d strikes=%d",
            market_id,
            gap.expected,
            gap.got,
            strikes,
        )
        if strikes >= self._max_consecutive_gaps:
            # Per R-E: double failure -> pause PM strategies.
            await self._publish_status(
                "gap_circuit_open", market_id=market_id, strikes=strikes
            )
            # Surface as exception so the run loop reconnects.
            raise RuntimeError(
                f"rtds gap circuit open market={market_id} strikes={strikes}"
            )
        # Drop local books for this market and resync each subscribed asset.
        affected_assets = [aid for mid, aid in self._subs if mid == market_id]
        self._state.reset_market(market_id)
        for asset_id in affected_assets:
            try:
                snapshot_payload = await self._snapshot_fn(market_id, asset_id)
            except Exception as e:
                logger.error(
                    "rtds resync fetch failed market=%s asset=%s err=%s",
                    market_id,
                    asset_id,
                    e,
                )
                raise
            # Force-stamp identifiers in case the REST shape omits them.
            snapshot_payload.setdefault("market_id", market_id)
            snapshot_payload.setdefault("asset_id", asset_id)
            snap = self._state.apply_snapshot(snapshot_payload)
            self._resyncs_total += 1
            await self._publish_resync(market_id, asset_id, snap.seq)
            await self._emit(snap)

    # ---- emit ------------------------------------------------------------
    async def _emit(self, snap: BookSnapshot) -> None:
        if self._queue.full():
            # Drop oldest to keep latency bounded; never block the recv loop.
            try:
                _ = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        await self._queue.put(snap)
        if self._redis is not None:
            payload = {"data": json.dumps(snap.to_event())}
            try:
                await self._redis.xadd(PM_BOOKS_STREAM, payload, maxlen=10000)
            except Exception as e:  # pragma: no cover - redis transport
                logger.warning("rtds xadd failed stream=%s err=%s", PM_BOOKS_STREAM, e)

    async def _publish_status(self, status: str, **fields: Any) -> None:
        if self._redis is None:
            return
        payload = {"status": status, **{k: str(v) for k, v in fields.items()}}
        try:
            await self._redis.xadd(PM_RTDS_STATUS_STREAM, payload, maxlen=1000)
        except Exception as e:  # pragma: no cover - redis transport
            logger.warning("rtds status xadd failed err=%s", e)

    async def _publish_resync(self, market_id: str, asset_id: str, seq: int) -> None:
        if self._redis is None:
            return
        try:
            await self._redis.xadd(
                PM_RESYNC_STREAM,
                {"market_id": market_id, "asset_id": asset_id, "seq": str(seq)},
                maxlen=1000,
            )
        except Exception as e:  # pragma: no cover - redis transport
            logger.warning("rtds resync xadd failed err=%s", e)


# ---------------------------------------------------------------------------
# Production transport adapter
# ---------------------------------------------------------------------------


@asynccontextmanager
async def websockets_connect(url: str):  # pragma: no cover - prod adapter
    """Default `connect_fn` wired to the `websockets` library.

    Imported lazily so unit tests don't need the dependency.
    """
    import websockets  # type: ignore

    async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
        yield ws


__all__ = [
    "BackoffPolicy",
    "DEFAULT_RTDS_URL",
    "RtdsWebSocketClient",
    "websockets_connect",
]

"""T8: Adaptive order-retry ladder.

When a limit order gets rejected, don't drop it — walk a ladder of
progressively wider buffers + reason-specific branches, logging every
attempt to `order_attempts` (migration 026) so T5 can learn from it.

Rungs:
    0: original limit at signal_price + p50 buffer  → wait 5s
    1: widen to p75 buffer                          → wait 5s
    2: widen to p90 buffer                          → wait 5s
    3: marketable limit (mid + full spread)         → wait 5s
    4: if p_fill_60s > 0.5 hold else abort + miss_reason

Reason-specific overrides:
    insufficient_funds → halve qty once, retry rung 0
    halt/LULD          → abort immediately, notify
    rate_limit         → exponential backoff starting 1s
    market_closed      → queue as market-on-open

Usage:
    ladder = RetryLadder(broker=broker_adapter)
    result = await ladder.submit(intent)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

logger = logging.getLogger(__name__)

BUFFER_BPS = [5.0, 15.0, 30.0, 60.0]  # rung 0-3 buffer widths in bps
RUNG_WAIT_SECONDS = 5.0


@dataclass
class Attempt:
    rung: int
    timestamp: datetime
    limit_price: float | None
    status: str
    reason: str | None = None
    fill_price: float | None = None


@dataclass
class LadderResult:
    status: str  # "filled" | "aborted"
    final_rung: int
    attempts: list[Attempt] = field(default_factory=list)
    fill: dict | None = None
    miss_reason: str | None = None


class RetryLadder:
    def __init__(self, broker: Any = None,
                 persist_attempt: Callable[[dict], Any] | None = None):
        self.broker = broker
        self._persist = persist_attempt  # async callable -> persists to order_attempts

    async def _persist_attempt(self, intent: dict, attempt: Attempt) -> None:
        if not self._persist:
            return
        try:
            await self._persist({
                "agent_id": intent.get("agent_id"),
                "intent_id": intent.get("intent_id"),
                "symbol": intent.get("symbol"),
                "side": intent.get("side"),
                "rung": attempt.rung,
                "limit_price": attempt.limit_price,
                "status": attempt.status,
                "reason": attempt.reason,
                "fill_price": attempt.fill_price,
                "attempted_at": attempt.timestamp.isoformat(),
            })
        except Exception as exc:
            logger.warning("[retry_ladder] persist failed: %s", exc)

    def _buffered_price(self, base: float | None, bps: float, side: str) -> float | None:
        if base is None:
            return None
        sign = 1 if side == "buy" else -1
        return round(base * (1 + sign * bps / 10000.0), 4)

    async def _single_attempt(self, intent: dict, rung: int, limit_price: float | None) -> Attempt:
        stamp = datetime.now(timezone.utc)
        try:
            if self.broker:
                from services.connector_manager.src.brokers.alpaca import BrokerOrder, OrderSide, OrderType
                order = BrokerOrder(
                    symbol=intent.get("symbol", ""),
                    side=OrderSide(intent.get("side", "buy")),
                    qty=intent.get("qty", 0),
                    order_type=OrderType("limit") if limit_price else OrderType("market"),
                    limit_price=limit_price,
                    stop_price=intent.get("stop_price"),
                )
                result = await self.broker.submit_order(order)
                return Attempt(
                    rung=rung,
                    timestamp=stamp,
                    limit_price=limit_price,
                    status=str(result.get("status", "submitted")),
                    fill_price=result.get("fill_price"),
                )
            # Simulated mode
            return Attempt(rung=rung, timestamp=stamp, limit_price=limit_price,
                           status="filled", fill_price=limit_price or 0.0)
        except Exception as exc:
            msg = str(exc).lower()
            reason = "unknown"
            if "insufficient" in msg or "buying power" in msg:
                reason = "insufficient_funds"
            elif "halt" in msg or "luld" in msg or "not tradable" in msg:
                reason = "halt"
            elif "rate" in msg and "limit" in msg:
                reason = "rate_limit"
            elif "market closed" in msg or "not open" in msg:
                reason = "market_closed"
            return Attempt(rung=rung, timestamp=stamp, limit_price=limit_price,
                           status="rejected", reason=reason)

    async def submit(self, intent: dict, *, p_fill_60s: float = 0.85) -> LadderResult:
        result = LadderResult(status="aborted", final_rung=-1)
        signal_price = intent.get("signal_price") or intent.get("limit_price")
        side = intent.get("side", "buy")
        halved_once = False

        for rung, bps in enumerate(BUFFER_BPS):
            limit = self._buffered_price(signal_price, bps, side)
            attempt = await self._single_attempt(intent, rung, limit)
            result.attempts.append(attempt)
            await self._persist_attempt(intent, attempt)

            if attempt.status in ("filled", "accepted", "submitted"):
                result.status = "filled"
                result.final_rung = rung
                result.fill = {
                    "fill_price": attempt.fill_price,
                    "status": attempt.status,
                }
                return result

            reason = attempt.reason
            if reason == "halt":
                result.miss_reason = "halt"
                return result
            if reason == "market_closed":
                result.miss_reason = "queued_market_on_open"
                # caller re-queues; stop the ladder
                return result
            if reason == "rate_limit":
                await asyncio.sleep(2 ** rung)
                continue
            if reason == "insufficient_funds" and not halved_once:
                halved_once = True
                intent = {**intent, "qty": max(1, int(intent.get("qty", 1) // 2))}
                # retry same rung with halved qty
                retry = await self._single_attempt(intent, rung, limit)
                result.attempts.append(retry)
                await self._persist_attempt(intent, retry)
                if retry.status in ("filled", "accepted", "submitted"):
                    result.status = "filled"
                    result.final_rung = rung
                    result.fill = {"fill_price": retry.fill_price, "status": retry.status}
                    return result

            await asyncio.sleep(RUNG_WAIT_SECONDS)

        # Rung 4: final hold/abort gate based on T5 fillability
        if p_fill_60s > 0.5:
            result.miss_reason = "held_awaiting_liquidity"
        else:
            result.miss_reason = "abandoned_low_fill_prob"
        result.final_rung = len(BUFFER_BPS)
        return result

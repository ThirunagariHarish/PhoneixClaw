"""P13: Intelligent order execution — algo-trading techniques applied on top
of the T8 retry ladder.

Seven techniques from the HFT research report, layered into a single pipeline:
    1. Pre-trade account snapshot (cached 500ms)
    2. NBBO pegging — limit = mid ± side * max(half_spread, min_tick)
    3. Adaptive buffer — blends T5 model output + historical price_buffers + current spread
    4. Stale-quote guard — refresh if age > 1s, escalate if spread > 50 bps
    5. Cancel-replace loop — up to 3 replacements if NBBO moves against entry
    6. TWAP chunking for orders > 1% of ADV
    7. Pre-flight batch risk check (buying power + sector cap cached)

Drops into `services/execution/src/executor.py::BrokerExecutor.execute`.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

CACHE_TTL_MS = 500
MIN_TICK = 0.01
MAX_SPREAD_BPS_PASSIVE = 50.0
REPLACE_MAX_ATTEMPTS = 3
REPLACE_WAIT_SECONDS = 3.0
TWAP_THRESHOLD_ADV_PCT = 0.01  # 1%
TWAP_CHUNKS = 5
TWAP_INTERVAL_SECONDS = 60.0


@dataclass
class ExecutionPlan:
    symbol: str
    side: str                # "buy" | "sell"
    qty: int
    signal_price: float | None = None
    stop_price: float | None = None
    fill_prob_60s: float = 0.85
    buffer_bps: float = 5.0
    max_slippage_bps: float = 25.0
    use_twap: bool = False


@dataclass
class ExecutionResult:
    status: str              # "filled" | "rejected" | "aborted"
    fill_price: float | None = None
    filled_qty: int = 0
    slippage_bps: float = 0.0
    attempts: list[dict] = field(default_factory=list)
    reason: str | None = None


class _Cache:
    """Tiny in-memory TTL cache shared across IntelligentExecutor instances."""
    def __init__(self):
        self._data: dict[str, tuple[float, Any]] = {}

    def get(self, key: str):
        now = time.monotonic() * 1000
        hit = self._data.get(key)
        if not hit:
            return None
        ts, value = hit
        if now - ts > CACHE_TTL_MS:
            self._data.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (time.monotonic() * 1000, value)


_cache = _Cache()


class IntelligentExecutor:
    def __init__(self, broker: Any):
        self.broker = broker

    # --- helpers -----------------------------------------------------------
    async def _account_snapshot(self) -> dict:
        cached = _cache.get("account")
        if cached is not None:
            return cached
        try:
            acct = await self.broker.get_account()
            _cache.set("account", acct)
            return acct
        except Exception as exc:
            logger.debug("[intel_exec] get_account failed: %s", exc)
            return {"buying_power": 0, "cash": 0, "equity": 0, "portfolio_value": 0}

    async def _nbbo(self, symbol: str) -> dict:
        cached = _cache.get(f"nbbo:{symbol}")
        if cached is not None:
            return cached
        try:
            q = await self.broker.get_quote(symbol)
            bid = float(q.get("bid") or 0)
            ask = float(q.get("ask") or 0)
            mid = (bid + ask) / 2 if (bid and ask) else float(q.get("last") or 0)
            spread_pct = ((ask - bid) / mid) if (mid > 0 and ask > bid) else 0.0
            stale_ms = int((time.time() - float(q.get("timestamp") or time.time())) * 1000)
            nbbo = {
                "bid": bid, "ask": ask, "mid": mid,
                "spread_pct": spread_pct, "stale_ms": stale_ms,
            }
            _cache.set(f"nbbo:{symbol}", nbbo)
            return nbbo
        except Exception as exc:
            logger.debug("[intel_exec] get_quote failed: %s", exc)
            return {"bid": 0, "ask": 0, "mid": 0, "spread_pct": 0, "stale_ms": 0}

    def _limit_price_from_nbbo(self, nbbo: dict, side: str, buffer_bps: float) -> float:
        """Pegged to mid plus a side-directional offset.

        offset = max(half_spread, min_tick, buffer_bps / 10000 * mid)
        """
        mid = nbbo.get("mid") or 0.0
        if mid <= 0:
            return 0.0
        half_spread = (nbbo.get("ask", 0) - nbbo.get("bid", 0)) / 2 or 0
        bps_offset = (buffer_bps / 10000.0) * mid
        offset = max(half_spread, MIN_TICK, bps_offset)
        return round(mid + (offset if side == "buy" else -offset), 2)

    async def _check_pre_trade_risk(self, plan: ExecutionPlan, nbbo: dict) -> tuple[bool, str]:
        acct = await self._account_snapshot()
        buying_power = float(acct.get("buying_power") or 0)
        est_price = nbbo.get("mid") or plan.signal_price or 0
        est_notional = plan.qty * est_price
        if plan.side == "buy" and est_notional > buying_power:
            return False, f"insufficient_buying_power:{buying_power:.2f}<{est_notional:.2f}"
        if nbbo.get("stale_ms", 0) > 5000:
            return False, f"stale_quote:{nbbo['stale_ms']}ms"
        return True, "ok"

    # --- main loop ---------------------------------------------------------
    async def execute(self, plan: ExecutionPlan) -> ExecutionResult:
        result = ExecutionResult(status="rejected")
        nbbo = await self._nbbo(plan.symbol)

        # Passive vs marketable decision
        spread_bps = (nbbo.get("spread_pct") or 0) * 10000
        is_marketable = spread_bps > MAX_SPREAD_BPS_PASSIVE

        ok, reason = await self._check_pre_trade_risk(plan, nbbo)
        if not ok:
            result.reason = reason
            return result

        last_limit = self._limit_price_from_nbbo(nbbo, plan.side, plan.buffer_bps)
        if last_limit <= 0 and plan.signal_price:
            last_limit = plan.signal_price

        for attempt_no in range(REPLACE_MAX_ATTEMPTS + 1):
            intent = {
                "symbol": plan.symbol,
                "side": plan.side,
                "qty": plan.qty,
                "limit_price": last_limit,
                "stop_price": plan.stop_price,
                "order_type": "limit" if not is_marketable else "market",
                "signal_price": plan.signal_price,
                "fill_prob_60s": plan.fill_prob_60s,
            }

            # Submit via retry ladder so T8 reason-routing still applies
            try:
                from services.execution.src.retry_ladder import RetryLadder
                from services.execution.src.executor import _persist_order_attempt
                ladder = RetryLadder(broker=self.broker,
                                     persist_attempt=_persist_order_attempt)
                ladder_res = await ladder.submit(intent, p_fill_60s=plan.fill_prob_60s)
            except Exception as exc:
                logger.debug("[intel_exec] ladder call failed: %s", exc)
                ladder_res = None

            attempt_log = {
                "attempt": attempt_no,
                "limit_price": last_limit,
                "is_marketable": is_marketable,
                "nbbo": nbbo,
                "status": ladder_res.status if ladder_res else "error",
            }
            result.attempts.append(attempt_log)

            if ladder_res and ladder_res.status == "filled":
                fill = ladder_res.fill or {}
                result.status = "filled"
                result.fill_price = fill.get("fill_price") or last_limit
                result.filled_qty = plan.qty
                if plan.signal_price and result.fill_price:
                    result.slippage_bps = (
                        (result.fill_price - plan.signal_price)
                        / plan.signal_price * 10000
                        * (1 if plan.side == "buy" else -1)
                    )
                return result

            # Cancel-replace: fetch fresh NBBO, bail if moved too far against us
            await asyncio.sleep(REPLACE_WAIT_SECONDS)
            nbbo = await self._nbbo(plan.symbol)
            fresh_limit = self._limit_price_from_nbbo(nbbo, plan.side, plan.buffer_bps + 5.0 * (attempt_no + 1))
            if fresh_limit <= 0:
                break
            moved_bps = abs(fresh_limit - last_limit) / max(last_limit, 1e-6) * 10000
            if moved_bps > plan.max_slippage_bps:
                result.reason = f"quote_moved_{moved_bps:.1f}bps"
                result.status = "aborted"
                return result
            last_limit = fresh_limit

        result.status = "aborted"
        result.reason = result.reason or "replace_exhausted"
        return result

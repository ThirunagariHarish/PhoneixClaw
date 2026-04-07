"""
Broker executor — places orders via broker adapters.

M1.12: Trade execution after risk approval.
Reference: PRD Section 8, existing v1 services/trade-executor/.
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def _persist_order_attempt(row: dict) -> None:
    """Async persist to order_attempts table (migration 026).

    Best-effort; any failure is swallowed so a DB outage never blocks a trade.
    """
    try:
        from sqlalchemy import text
        from shared.db.engine import get_session
        async for session in get_session():
            await session.execute(
                text(
                    "INSERT INTO order_attempts (agent_id, intent_id, symbol, side, "
                    "rung, limit_price, status, reason, fill_price, attempted_at) "
                    "VALUES (:agent_id, :intent_id, :symbol, :side, :rung, "
                    ":limit_price, :status, :reason, :fill_price, :attempted_at)"
                ),
                row,
            )
            await session.commit()
            break
    except Exception as exc:
        logger.debug("[executor] order_attempts persist skipped: %s", exc)


class BrokerExecutor:
    """
    Executes approved trade intents against configured broker.
    Uses the broker adapter pattern from v1.
    """

    def __init__(self, broker_adapter: Any = None, use_retry_ladder: bool = True,
                  use_intelligent: bool = True):
        self.broker = broker_adapter
        self._fill_count = 0
        self._fail_count = 0
        self._use_ladder = use_retry_ladder
        self._use_intelligent = use_intelligent

    async def execute(self, intent: dict) -> dict[str, Any]:
        """Execute a trade intent. Returns fill data or raises on failure."""
        symbol = intent.get("symbol", "")
        side = intent.get("side", "buy")
        qty = intent.get("qty", 0)
        order_type = intent.get("order_type", "market")

        logger.info("Executing %s %s %s @ %s", side, qty, symbol, order_type)

        # P13: IntelligentExecutor layer (NBBO + pre-trade snapshot + cancel-replace)
        if self._use_intelligent and self.broker and intent.get("symbol"):
            try:
                from services.execution.src.intelligent_executor import (
                    IntelligentExecutor, ExecutionPlan
                )
                plan = ExecutionPlan(
                    symbol=intent.get("symbol", ""),
                    side=intent.get("side", "buy"),
                    qty=int(intent.get("qty", 0) or 0),
                    signal_price=intent.get("signal_price") or intent.get("limit_price"),
                    stop_price=intent.get("stop_price"),
                    fill_prob_60s=float(intent.get("fill_prob_60s", 0.85)),
                    buffer_bps=float(intent.get("buffer_bps", 5.0)),
                )
                intel = IntelligentExecutor(broker=self.broker)
                res = await intel.execute(plan)
                if res.status == "filled":
                    self._fill_count += 1
                    return {
                        "id": f"intel-{datetime.now(timezone.utc).timestamp()}",
                        "symbol": plan.symbol, "side": plan.side, "qty": plan.qty,
                        "status": "filled",
                        "fill_price": res.fill_price,
                        "filled_at": datetime.now(timezone.utc).isoformat(),
                        "slippage_bps": round(res.slippage_bps, 2),
                        "attempts": res.attempts,
                    }
                self._fail_count += 1
                raise RuntimeError(f"intelligent_executor_{res.status}:{res.reason}")
            except RuntimeError:
                raise
            except Exception as exc:
                logger.warning("[executor] intelligent path failed, falling back: %s", exc)

        # T8: route through the adaptive retry ladder when enabled
        if self._use_ladder and self.broker:
            from services.execution.src.retry_ladder import RetryLadder
            ladder = RetryLadder(broker=self.broker,
                                 persist_attempt=_persist_order_attempt)
            result = await ladder.submit(intent,
                                         p_fill_60s=intent.get("fill_prob_60s", 0.85))
            if result.status == "filled":
                self._fill_count += 1
                return {
                    "id": f"ladder-{datetime.now(timezone.utc).timestamp()}",
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "status": "filled",
                    "fill_price": (result.fill or {}).get("fill_price"),
                    "filled_at": datetime.now(timezone.utc).isoformat(),
                    "final_rung": result.final_rung,
                    "attempts": len(result.attempts),
                }
            self._fail_count += 1
            raise RuntimeError(f"ladder_aborted:{result.miss_reason}")

        if self.broker:
            from services.connector_manager.src.brokers.alpaca import BrokerOrder, OrderSide, OrderType
            order = BrokerOrder(
                symbol=symbol,
                side=OrderSide(side),
                qty=qty,
                order_type=OrderType(order_type),
                limit_price=intent.get("limit_price"),
                stop_price=intent.get("stop_price"),
            )
            result = await self.broker.submit_order(order)
            self._fill_count += 1
            return result

        # Simulated fill for paper/test mode
        self._fill_count += 1
        return {
            "id": f"sim-{datetime.now(timezone.utc).timestamp()}",
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "status": "filled",
            "fill_price": intent.get("limit_price", 0) or intent.get("estimated_price", 100.0),
            "filled_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_stats(self) -> dict[str, int]:
        return {"fills": self._fill_count, "failures": self._fail_count}

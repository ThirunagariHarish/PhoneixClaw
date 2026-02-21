"""Poll broker for order fill status and update Trade + create Position records."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy import update as sa_update

from shared.broker.adapter import BrokerAdapter
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Position, Trade

logger = logging.getLogger(__name__)

POLL_INTERVAL = 5
MAX_POLLS = 60
PARTIAL_FILL_THRESHOLD = 0.0


class FillTracker:
    """Track pending broker orders until they fill, partially fill, or expire."""

    def __init__(self) -> None:
        self._pending: list[dict] = []
        self._running = False

    async def track(self, order_id: str, trade: dict, broker: BrokerAdapter) -> None:
        self._pending.append({
            "order_id": order_id,
            "trade": trade,
            "broker": broker,
            "polls": 0,
        })

    async def start(self) -> None:
        self._running = True
        logger.info("Fill tracker started")

    async def stop(self) -> None:
        self._running = False

    async def run(self) -> None:
        while self._running:
            await self._poll_cycle()
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_cycle(self) -> None:
        if not self._pending:
            return

        done = []
        for item in self._pending:
            item["polls"] += 1
            try:
                status = await item["broker"].get_order_status(item["order_id"])
                fill_status = status.get("status", "").upper()
                filled_qty = status.get("filled_qty", 0)
                fill_price = status.get("fill_price", 0)

                if fill_status == "FILLED":
                    await self._on_filled(item["trade"], fill_price, filled_qty)
                    done.append(item)
                elif fill_status == "PARTIALLY_FILLED" and filled_qty > PARTIAL_FILL_THRESHOLD:
                    await self._on_partial_fill(item["trade"], fill_price, filled_qty)
                elif fill_status in ("CANCELLED", "REJECTED", "EXPIRED"):
                    await self._on_cancelled(item["trade"], fill_status, filled_qty, fill_price)
                    done.append(item)
                elif item["polls"] >= MAX_POLLS:
                    logger.warning("Max polls reached for order %s — marking stale", item["order_id"])
                    await self._on_cancelled(item["trade"], "STALE", filled_qty, fill_price)
                    done.append(item)
            except Exception:
                logger.exception("Error polling order %s", item["order_id"])

        for item in done:
            self._pending.remove(item)

    async def _on_filled(self, trade: dict, fill_price: float, filled_qty: int) -> None:
        trade_id = trade.get("trade_id")
        logger.info("Order FILLED: trade=%s price=%.2f qty=%d", trade_id, fill_price, filled_qty)

        async with AsyncSessionLocal() as session:
            await session.execute(
                sa_update(Trade)
                .where(Trade.trade_id == uuid.UUID(trade_id))
                .values(
                    fill_price=fill_price,
                    resolved_quantity=filled_qty,
                    status="FILLED",
                )
            )
            await session.commit()

        await self._open_position(trade, fill_price, filled_qty)

    async def _on_partial_fill(self, trade: dict, fill_price: float, filled_qty: int) -> None:
        trade_id = trade.get("trade_id")
        logger.info("PARTIAL fill: trade=%s filled=%d price=%.2f", trade_id, filled_qty, fill_price)

        async with AsyncSessionLocal() as session:
            await session.execute(
                sa_update(Trade)
                .where(Trade.trade_id == uuid.UUID(trade_id))
                .values(
                    fill_price=fill_price,
                    resolved_quantity=filled_qty,
                    status="PARTIAL_FILL",
                )
            )
            await session.commit()

    async def _on_cancelled(
        self, trade: dict, reason: str, filled_qty: int, fill_price: float
    ) -> None:
        trade_id = trade.get("trade_id")
        logger.info("Order %s: trade=%s", reason, trade_id)

        async with AsyncSessionLocal() as session:
            vals: dict = {"status": reason}
            if filled_qty > 0:
                vals["fill_price"] = fill_price
                vals["resolved_quantity"] = filled_qty
            await session.execute(
                sa_update(Trade)
                .where(Trade.trade_id == uuid.UUID(trade_id))
                .values(**vals)
            )
            await session.commit()

        if filled_qty > 0:
            await self._open_position(trade, fill_price, filled_qty)

    async def _open_position(self, trade: dict, fill_price: float, quantity: int) -> None:
        """Create a Position row in the database for a filled (or partially filled) order."""
        if trade.get("action", "").upper() != "BUY":
            return

        try:
            user_id = trade.get("user_id")
            ta_id = trade.get("trading_account_id")
            if not user_id or not ta_id:
                return

            exp = None
            if trade.get("expiration"):
                try:
                    exp = datetime.strptime(trade["expiration"], "%Y-%m-%d")
                except (ValueError, TypeError):
                    pass

            async with AsyncSessionLocal() as session:
                existing = await session.execute(
                    select(Position).where(
                        Position.user_id == uuid.UUID(user_id),
                        Position.broker_symbol == (trade.get("broker_symbol") or ""),
                        Position.status == "OPEN",
                    )
                )
                pos = existing.scalar_one_or_none()

                if pos:
                    total_cost = float(pos.total_cost) + (fill_price * quantity * 100)
                    total_qty = pos.quantity + quantity
                    pos.avg_entry_price = total_cost / (total_qty * 100) if total_qty else fill_price
                    pos.quantity = total_qty
                    pos.total_cost = total_cost
                    await session.commit()
                    logger.info("Updated existing position %d — new qty=%d", pos.id, total_qty)
                else:
                    new_pos = Position(
                        user_id=uuid.UUID(user_id),
                        trading_account_id=uuid.UUID(ta_id),
                        ticker=trade.get("ticker", ""),
                        strike=trade.get("strike", 0),
                        option_type=trade.get("option_type", "CALL"),
                        expiration=exp or datetime.now(timezone.utc),
                        quantity=quantity,
                        avg_entry_price=fill_price,
                        total_cost=fill_price * quantity * 100,
                        profit_target=trade.get("profit_target", 0.30),
                        stop_loss=trade.get("stop_loss", 0.20),
                        high_water_mark=fill_price,
                        broker_symbol=trade.get("broker_symbol", ""),
                        status="OPEN",
                    )
                    session.add(new_pos)
                    await session.commit()
                    logger.info("Opened new position for %s", trade.get("ticker"))
        except Exception:
            logger.exception("Failed to open position for trade %s", trade.get("trade_id"))

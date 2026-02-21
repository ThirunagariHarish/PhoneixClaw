import asyncio
import logging

from sqlalchemy import select

from services.position_monitor.src.exit_engine import ExitEngine
from shared.broker.factory import create_broker_adapter
from shared.config.base_config import config
from shared.feature_flags import feature_flags
from shared.kafka_utils.producer import KafkaProducerWrapper
from shared.models.database import AsyncSessionLocal
from shared.models.trade import Position, TradingAccount

logger = logging.getLogger(__name__)


class PositionMonitorService:
    def __init__(self):
        self.producer = KafkaProducerWrapper()
        self.exit_engine = ExitEngine()
        self._running = False
        self._broker_cache: dict[str, object] = {}
        self._poll_interval = config.monitor.poll_interval_seconds

    async def start(self):
        await self.producer.start()
        self._running = True
        logger.info("Position monitor service started (poll_interval=%ds)", self._poll_interval)

    async def stop(self):
        self._running = False
        await self.producer.stop()

    async def run(self):
        while self._running:
            try:
                await self._poll_cycle()
            except Exception:
                logger.exception("Position monitor poll cycle failed")
            await asyncio.sleep(self._poll_interval)

    async def _poll_cycle(self):
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Position).where(Position.status == "OPEN")
            )
            open_positions = result.scalars().all()

        if not open_positions:
            return

        accounts_to_positions: dict[str, list] = {}
        for pos in open_positions:
            ta_id = str(pos.trading_account_id)
            accounts_to_positions.setdefault(ta_id, []).append(pos)

        for ta_id, positions in accounts_to_positions.items():
            broker = await self._get_broker(ta_id)
            if not broker:
                continue

            try:
                broker_positions = await broker.get_positions()
                price_map = {p["symbol"]: p["current_price"] for p in broker_positions}
            except Exception:
                logger.exception("Failed to fetch positions from broker for account %s", ta_id)
                continue

            for pos in positions:
                current_price = price_map.get(pos.broker_symbol)
                if current_price is None:
                    continue

                pos_dict = {
                    "id": pos.id,
                    "avg_entry_price": float(pos.avg_entry_price),
                    "profit_target": float(pos.profit_target),
                    "stop_loss": float(pos.stop_loss),
                    "high_water_mark": float(pos.high_water_mark) if pos.high_water_mark else None,
                    "broker_symbol": pos.broker_symbol,
                    "user_id": pos.user_id,
                    "trading_account_id": pos.trading_account_id,
                    "ticker": pos.ticker,
                    "quantity": pos.quantity,
                    "trailing_stop_enabled": (
                        config.monitor.trailing_stop_enabled
                        and feature_flags.is_enabled("trailing_stops", str(pos.user_id))
                    ),
                    "trailing_stop_offset": config.monitor.trailing_stop_offset,
                }

                new_hwm = self.exit_engine.update_high_water_mark(
                    pos_dict.get("high_water_mark"), current_price
                )
                if new_hwm != pos_dict.get("high_water_mark"):
                    pos_dict["high_water_mark"] = new_hwm
                    async with AsyncSessionLocal() as session:
                        db_pos = await session.get(Position, pos.id)
                        if db_pos:
                            db_pos.high_water_mark = new_hwm
                            await session.commit()

                signal = self.exit_engine.evaluate_position(pos_dict, current_price)
                if signal:
                    await self._publish_exit_signal(pos_dict, signal)

    async def _get_broker(self, ta_id: str):
        if ta_id in self._broker_cache:
            return self._broker_cache[ta_id]
        async with AsyncSessionLocal() as session:
            import uuid as _uuid
            account = await session.get(TradingAccount, _uuid.UUID(ta_id))
            if not account:
                return None
            broker = create_broker_adapter(
                account.broker_type, account.credentials_encrypted, account.paper_mode,
            )
            self._broker_cache[ta_id] = broker
            return broker

    async def _publish_exit_signal(self, position: dict, signal):
        exit_msg = {
            "position_id": signal.position_id,
            "reason": signal.reason,
            "trigger_price": signal.trigger_price,
            "user_id": str(position.get("user_id", "")),
            "trading_account_id": str(position.get("trading_account_id", "")),
            "ticker": position.get("ticker", ""),
            "broker_symbol": position.get("broker_symbol", ""),
            "quantity": position.get("quantity", 0),
        }
        headers = []
        uid = str(position.get("user_id", ""))
        if uid:
            headers.append(("user_id", uid.encode("utf-8")))
        await self.producer.send("exit-signals", value=exit_msg, headers=headers or None)
        logger.info(
            "Exit signal: %s for position %s (price=%.2f)",
            signal.reason, signal.position_id, signal.trigger_price,
        )

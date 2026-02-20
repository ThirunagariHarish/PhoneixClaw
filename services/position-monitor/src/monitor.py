import logging

from services.position_monitor.src.exit_engine import ExitEngine
from shared.kafka_utils.producer import KafkaProducerWrapper

logger = logging.getLogger(__name__)


class PositionMonitorService:
    def __init__(self):
        self.producer = KafkaProducerWrapper()
        self.exit_engine = ExitEngine()
        self._running = False
        self._price_cache: dict[str, float] = {}

    async def start(self):
        await self.producer.start()
        self._running = True
        logger.info("Position monitor service started")

    async def stop(self):
        self._running = False
        await self.producer.stop()

    def update_price(self, symbol: str, price: float):
        self._price_cache[symbol] = price

    async def check_positions(self, positions: list[dict]):
        for pos in positions:
            symbol = pos.get("broker_symbol", "")
            current_price = self._price_cache.get(symbol)
            if current_price is None:
                continue

            new_hwm = self.exit_engine.update_high_water_mark(pos.get("high_water_mark"), current_price)
            if new_hwm != pos.get("high_water_mark"):
                pos["high_water_mark"] = new_hwm

            signal = self.exit_engine.evaluate_position(pos, current_price)
            if signal:
                await self._publish_exit_signal(pos, signal)

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

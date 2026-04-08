"""
Trade intent consumer — reads from Redis Streams and processes through risk checks.

M1.12: Execution Service.
Reference: PRD Section 8, ArchitecturePlan §5.
"""

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class TradeIntentConsumer:
    """
    Consumes trade intents from the 'trade-intents' Redis Stream.
    Each intent goes through a 3-layer risk check chain before execution.
    """

    STREAM_KEY = "phoenix:trade-intents"
    GROUP_NAME = "execution-service"
    CONSUMER_NAME = "exec-worker-1"

    def __init__(self, redis_client: Any, risk_chain: "RiskCheckChain", executor: "BrokerExecutor"):
        self.redis = redis_client
        self.risk_chain = risk_chain
        self.executor = executor
        self._running = False

    async def setup(self) -> None:
        """Create consumer group if it doesn't exist."""
        try:
            await self.redis.xgroup_create(
                self.STREAM_KEY, self.GROUP_NAME, id="0", mkstream=True
            )
        except Exception:
            pass  # Group already exists

    async def start(self) -> None:
        """Start consuming trade intents."""
        self._running = True
        await self.setup()
        logger.info("Execution consumer started on stream %s", self.STREAM_KEY)

        while self._running:
            try:
                messages = await self.redis.xreadgroup(
                    self.GROUP_NAME,
                    self.CONSUMER_NAME,
                    {self.STREAM_KEY: ">"},
                    count=10,
                    block=5000,
                )
                for stream, entries in messages:
                    for msg_id, data in entries:
                        await self._process_intent(msg_id, data)
                        await self.redis.xack(self.STREAM_KEY, self.GROUP_NAME, msg_id)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Consumer error: %s", e)
                await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False

    async def _process_intent(self, msg_id: str, data: dict) -> None:
        """Process a single trade intent through risk checks and execution."""
        intent = json.loads(data.get(b"payload", data.get("payload", "{}")))
        intent_id = intent.get("id", msg_id)
        logger.info("Processing trade intent %s: %s %s %s",
                     intent_id, intent.get("side"), intent.get("qty"), intent.get("symbol"))

        # 3-layer risk check
        risk_result = self.risk_chain.evaluate(intent)
        if not risk_result["approved"]:
            logger.warning("Trade intent %s rejected: %s", intent_id, risk_result["reason"])
            return

        # Execute the trade
        try:
            fill = await self.executor.execute(intent)
            logger.info("Trade intent %s filled: %s", intent_id, fill)
        except Exception as e:
            logger.error("Execution failed for %s: %s", intent_id, e)

"""Backtest Worker — Redis stream consumer that runs backtests in isolated pod.

Consumes from backtest:requests stream, instantiates BacktestOrchestrator,
runs the pipeline, and ACKs on completion.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path

# Ensure PYTHONPATH is set
if "/app" not in sys.path:
    sys.path.insert(0, "/app")

from services.backtest_worker.src.consumer import get_consumer

# Import BacktestOrchestrator from apps/api (copied to image at build time)
from apps.api.src.services.backtest_orchestrator import BacktestOrchestrator

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BACKTEST_DATA_DIR = Path(os.getenv("PHOENIX_BACKTEST_DATA_DIR", "/var/lib/phoenix/backtests"))
MAX_RETRIES = 3


async def handle_backtest_request(message_id: str, payload: dict) -> bool:
    """Process a single backtest request.

    Returns True on success (or final failure), False on transient error.
    """
    try:
        agent_id_str = payload.get("agent_id")
        backtest_id_str = payload.get("backtest_id")
        session_id_str = payload.get("session_id")
        config = payload.get("config", {})

        if not agent_id_str or not session_id_str:
            logger.error("Invalid payload (missing agent_id or session_id): %s", payload)
            return True  # Terminal failure, ACK to discard

        agent_id = uuid.UUID(agent_id_str)
        session_id = uuid.UUID(session_id_str)

        # Work directory: /var/lib/phoenix/backtests/<agent_id>/<session_id>
        work_dir = BACKTEST_DATA_DIR / str(agent_id) / str(session_id)
        work_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Starting backtest: agent=%s session=%s backtest=%s work_dir=%s",
            agent_id, session_id, backtest_id_str, work_dir,
        )

        # Instantiate and run orchestrator
        orchestrator = BacktestOrchestrator(
            agent_id=agent_id,
            session_id=session_id,
            work_dir=work_dir,
            config=config,
            enabled_algorithms=config.get("enabled_algorithms"),
        )

        result = await orchestrator.run()
        status = result.get("status")

        if status == "completed":
            logger.info(
                "Backtest completed: agent=%s session=%s elapsed=%.1fs",
                agent_id, session_id, result.get("elapsed_seconds", 0),
            )
            return True
        elif status == "failed":
            logger.error(
                "Backtest failed: agent=%s session=%s failed_step=%s",
                agent_id, session_id, result.get("failed_step"),
            )
            return True  # Terminal failure, ACK
        else:
            logger.warning("Backtest returned unexpected status: %s", status)
            return False  # Retry

    except Exception as e:
        logger.exception("Unhandled error processing backtest request %s: %s", message_id, e)
        return False  # Retry on unexpected errors


async def main() -> None:
    """Main worker loop."""
    logger.info("Backtest worker starting")

    consumer = get_consumer()
    await consumer.connect()

    # Track retries per message (in-memory is fine, pod restart resets)
    retry_counts: dict[str, int] = {}

    try:
        async for message_id, payload in consumer.consume():
            logger.info("Received message %s: %s", message_id, payload)

            success = await handle_backtest_request(message_id, payload)

            if success:
                # ACK and discard
                await consumer.ack(message_id)
                logger.info("ACKed message %s", message_id)
                retry_counts.pop(message_id, None)
            else:
                # Transient error — check retry count
                retry_counts[message_id] = retry_counts.get(message_id, 0) + 1

                if retry_counts[message_id] >= MAX_RETRIES:
                    logger.error(
                        "Message %s failed after %d retries, ACKing to discard",
                        message_id, MAX_RETRIES,
                    )
                    await consumer.ack(message_id)
                    retry_counts.pop(message_id, None)
                else:
                    logger.warning(
                        "Message %s failed (retry %d/%d), leaving in PEL for later claim",
                        message_id, retry_counts[message_id], MAX_RETRIES,
                    )
                    # Do NOT ACK — leave in PEL for another consumer or retry

    except asyncio.CancelledError:
        logger.info("Worker cancelled, shutting down")
    except Exception as e:
        logger.exception("Fatal error in worker loop: %s", e)
    finally:
        await consumer.close()


if __name__ == "__main__":
    asyncio.run(main())

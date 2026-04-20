from __future__ import annotations
import asyncio
import logging
import signal
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class GracefulShutdown:
    """Manages graceful shutdown on SIGTERM/SIGINT."""

    def __init__(self) -> None:
        self._shutdown_event = asyncio.Event()
        self._cleanup_handlers: list[Callable[[], Awaitable[None]]] = []

    def register(self, handler: Callable[[], Awaitable[None]]) -> None:
        self._cleanup_handlers.append(handler)

    @property
    def is_shutting_down(self) -> bool:
        return self._shutdown_event.is_set()

    async def wait(self) -> None:
        await self._shutdown_event.wait()

    def _signal_handler(self) -> None:
        logger.info("Shutdown signal received, starting graceful shutdown...")
        self._shutdown_event.set()

    def install_signals(self, loop: asyncio.AbstractEventLoop | None = None) -> None:
        _loop = loop or asyncio.get_event_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            _loop.add_signal_handler(sig, self._signal_handler)

    async def run_cleanup(self, timeout: float = 30.0) -> None:
        logger.info("Running %d cleanup handlers (timeout=%.1fs)...", len(self._cleanup_handlers), timeout)
        try:
            await asyncio.wait_for(
                asyncio.gather(*(h() for h in self._cleanup_handlers), return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Cleanup timed out after %.1fs", timeout)
        logger.info("Shutdown complete")


shutdown = GracefulShutdown()

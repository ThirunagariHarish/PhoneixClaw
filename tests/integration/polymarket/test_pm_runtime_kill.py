"""Integration test for PMAgentRuntime kill-switch propagation (B2).

A fake redis stream publishes a kill-switch activate event; the runtime's
listener loop must trip the shared flag and the agent must observe the
halt within 2 seconds.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from services.orchestrator.src.pm_agent_runtime import (
    KILL_SWITCH_STREAM,
    PMAgentRuntime,
)


class _FakeAgent:
    """Tiny agent that does fake work each cycle and watches a flag."""

    def __init__(self) -> None:
        self.cycles = 0
        self.halted_after: float | None = None
        self.kill_switch_fn = lambda: False

    async def run_cycle(self) -> list:
        # Simulate a non-trivial leg latency so the kill switch has time to fire.
        await asyncio.sleep(0.02)
        self.cycles += 1
        if self.kill_switch_fn():
            self.halted_after = time.perf_counter()
            return []
        # Pretend we did some work.
        return [{"ok": True}]


class _FakeRedis:
    """xread-compatible fake. Holds a single pending entry then blocks."""

    def __init__(self) -> None:
        self._pending: list[tuple[str, dict]] = []
        self._delivered = False

    def publish(self, action: str, reason: str = "test") -> None:
        self._pending.append((f"1-{len(self._pending)}", {"action": action, "reason": reason}))

    async def xread(self, streams, count=10, block=1000):
        # Single delivery — drain pending then sleep until cancelled.
        if self._pending and not self._delivered:
            self._delivered = True
            entries = list(self._pending)
            self._pending.clear()
            return [(KILL_SWITCH_STREAM, entries)]
        await asyncio.sleep(block / 1000.0)
        return []


@pytest.mark.asyncio
async def test_pm_runtime_halts_on_kill_switch_stream_event():
    agent = _FakeAgent()
    redis_client = _FakeRedis()
    runtime = PMAgentRuntime(agent=agent, redis_client=redis_client, consumer_block_ms=50)

    async def driver() -> None:
        # Kick the runtime, then publish a kill event after 200ms.
        task = asyncio.create_task(runtime.run())
        await asyncio.sleep(0.2)
        publish_t = time.perf_counter()
        redis_client.publish("activate", reason="chaos")

        # Wait until the agent observes the halt or 2s elapses.
        deadline = publish_t + 2.0
        while time.perf_counter() < deadline:
            if agent.halted_after is not None:
                break
            await asyncio.sleep(0.01)
        runtime.stop()
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, BaseException):
            pass

        assert agent.halted_after is not None, "agent did not observe kill switch within 2s"
        propagation = agent.halted_after - publish_t
        assert propagation < 2.0, f"kill switch propagation {propagation:.3f}s exceeds 2s SLA"
        assert runtime.kill_switch_fn() is True

    await driver()

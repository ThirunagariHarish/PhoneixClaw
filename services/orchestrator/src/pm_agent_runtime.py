"""Polymarket agent runtime — production wrapper around SumToOneArbAgent.

Reference: docs/architecture/polymarket-tab.md Phase 9, decision #3, and
Cortex review blocker B2.

This module is the thin glue that the orchestrator service uses to actually
*run* a `SumToOneArbAgent` in production:

- It owns the asyncio loop that drives `agent.run_cycle()` back-to-back.
- It subscribes to the `stream:kill-switch` Redis stream and flips a shared
  asyncio flag whenever an `activate` message arrives. The agent's
  `kill_switch_fn` reads that flag, so propagation from Redis -> halt is
  bounded by the longest in-flight broker call (the chaos test asserts
  <2s, with a <1s operational target).
- The runtime is intentionally testable: a unit test can construct it with
  a fake redis and a fake agent and assert halt latency without any real
  service.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)


KILL_SWITCH_STREAM = "stream:kill-switch"


class _AgentLike(Protocol):
    async def run_cycle(self) -> Any: ...


@dataclass
class PMAgentRuntime:
    """Drive a single PM agent + listen for kill-switch events.

    The agent must expose `run_cycle()` and accept a `kill_switch_fn`
    callable returning `bool`. The runtime sets that callable to read the
    shared `_kill_flag` so the agent can halt mid-cycle without any IPC.
    """

    agent: _AgentLike
    redis_client: Any  # redis.asyncio.Redis-like
    cycle_idle_sleep_s: float = 0.05
    consumer_block_ms: int = 1000

    _kill_flag: dict = field(default_factory=lambda: {"on": False})
    _stop: asyncio.Event = field(default_factory=asyncio.Event)
    _last_id: str = "$"

    def kill_switch_fn(self) -> bool:
        return bool(self._kill_flag["on"])

    def trip(self, reason: str = "manual") -> None:
        if not self._kill_flag["on"]:
            logger.warning("pm_agent_runtime kill switch tripped: %s", reason)
        self._kill_flag["on"] = True

    def rearm(self) -> None:
        self._kill_flag["on"] = False

    def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------
    # Loops
    # ------------------------------------------------------------------
    async def _agent_loop(self) -> None:
        # Wire the shared flag into the agent. We do this here so callers
        # cannot accidentally construct the agent with a stale closure.
        try:
            self.agent.kill_switch_fn = self.kill_switch_fn  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover - protocol fallback
            pass

        while not self._stop.is_set():
            try:
                await self.agent.run_cycle()
            except Exception:
                logger.exception("pm_agent_runtime: run_cycle raised")
            if self._kill_flag["on"]:
                # Yield aggressively while halted so kill-switch propagation
                # observation can fire on the next loop tick.
                await asyncio.sleep(0)
            else:
                await asyncio.sleep(self.cycle_idle_sleep_s)

    async def _kill_switch_loop(self) -> None:
        last_id = self._last_id
        while not self._stop.is_set():
            try:
                results = await self.redis_client.xread(
                    {KILL_SWITCH_STREAM: last_id},
                    count=10,
                    block=self.consumer_block_ms,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("pm_agent_runtime: xread failed: %s", e)
                await asyncio.sleep(0.5)
                continue
            if not results:
                continue
            for _stream_name, entries in results:
                for entry_id, data in entries:
                    last_id = entry_id
                    action = (data.get("action") or data.get("type") or "").lower()
                    if action in ("activate", "trip", "halt", "kill"):
                        self.trip(reason=str(data.get("reason", "stream")))
                    elif action in ("deactivate", "rearm", "clear"):
                        self.rearm()

    async def run(self) -> None:
        """Run agent + kill-switch listener until `stop()` is called."""
        await asyncio.gather(self._agent_loop(), self._kill_switch_loop())


def build_runtime(
    *,
    agent: _AgentLike,
    redis_client: Any,
) -> PMAgentRuntime:
    """Factory used by the orchestrator entrypoint to wire the runtime."""
    return PMAgentRuntime(agent=agent, redis_client=redis_client)


__all__ = ["PMAgentRuntime", "KILL_SWITCH_STREAM", "build_runtime"]

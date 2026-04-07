"""Morning routine orchestrator — coordinates pre-market analysis across all agents.

Triggered by Claude Code cron at 9:00 AM ET (30 minutes before market open).

Flow:
1. Get all RUNNING / PAPER agents from DB
2. Wake each agent (notification)
3. Send each agent a "morning_research" task via gateway.send_task()
4. Agents run pre_market_analyzer.py independently
5. Agents broadcast `morning_research` knowledge to peers
6. Compile briefing and dispatch via WhatsApp + dashboard
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

logger = logging.getLogger(__name__)


class MorningRoutineOrchestrator:
    """Coordinates the pre-market routine across all live agents."""

    async def execute(self) -> dict:
        """Run the morning routine.

        Returns a summary of what happened.
        """
        from shared.db.engine import get_session
        from shared.db.models.agent import Agent

        results = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "agents_eligible": 0,
            "agents_started": 0,
            "agents_woken": 0,
            "agents_triggered": 0,
            "briefing_sent": False,
            "errors": [],
        }

        # P10 revised: include ONLY statuses that gateway.create_analyst actually accepts
        # so we don't silently fail inside the gateway. Agents in CREATED/IDLE are skipped
        # with a warning — they haven't been approved yet and shouldn't auto-wake.
        WAKE_ELIGIBLE = ["BACKTEST_COMPLETE", "APPROVED", "PAPER", "RUNNING", "PAUSED"]
        agents: list = []
        skipped: list[dict] = []
        async for session in get_session():
            query = select(Agent).where(Agent.status.in_(WAKE_ELIGIBLE))
            rows = await session.execute(query)
            agents = list(rows.scalars().all())

            # Also surface CREATED agents so the user sees them in the response
            skipped_query = select(Agent).where(
                Agent.status.in_(["CREATED", "IDLE", "STOPPED"])
            )
            sk_rows = await session.execute(skipped_query)
            skipped = [
                {"id": str(a.id), "name": a.name, "status": a.status}
                for a in sk_rows.scalars().all()
            ]

        results["agents_eligible"] = len(agents)
        results["agents_skipped"] = skipped
        if skipped:
            logger.warning(
                "[morning] Skipping %d agents not in wake-eligible status: %s",
                len(skipped),
                ", ".join(f"{s['name']}({s['status']})" for s in skipped[:10]),
            )

        if not agents:
            results["message"] = (
                f"No wake-eligible agents (status in {WAKE_ELIGIBLE}). "
                f"{len(skipped)} agents skipped — approve them first."
            )
            return results

        logger.info("Morning routine: %d active agents", len(agents))

        agent_summaries = []
        for agent in agents:
            try:
                # 1. Send wake greeting via notification
                await self._greet_agent(agent)
                results["agents_woken"] += 1

                # 2. Trigger pre-market analysis via send_task
                triggered = await self._trigger_pre_market(agent)
                if triggered:
                    results["agents_triggered"] += 1
                    if triggered.get("auto_started"):
                        results["agents_started"] += 1
                    agent_summaries.append({
                        "agent_id": str(agent.id),
                        "name": agent.name,
                        "channel": agent.channel_name or "",
                        "character": (agent.manifest or {}).get("identity", {}).get("character", "unknown"),
                        "task_id": triggered.get("task_id"),
                    })
            except Exception as exc:
                error = f"{agent.name}: {str(exc)[:200]}"
                results["errors"].append(error)
                logger.error("Morning routine error for %s: %s", agent.id, exc)

        # 3. Compile briefing
        if agent_summaries:
            briefing = self._compile_briefing(agent_summaries)
            await self._dispatch_briefing(briefing)
            results["briefing_sent"] = True
            results["briefing_preview"] = briefing[:500]

        results["completed_at"] = datetime.now(timezone.utc).isoformat()
        results["agent_summaries"] = agent_summaries
        return results

    async def _greet_agent(self, agent) -> None:
        """Send wake-up greeting via notification dispatcher."""
        try:
            from apps.api.src.services.notification_dispatcher import notification_dispatcher
            await notification_dispatcher.dispatch(
                event_type="agent_wake",
                agent_id=str(agent.id),
                title=f"{agent.name} is awake",
                body=(f"Good morning! {agent.name} is starting morning research for "
                      f"{agent.channel_name or 'configured channels'}."),
                channels=["whatsapp", "ws", "db"],
                data={"agent_name": agent.name, "channel_name": agent.channel_name},
            )
        except Exception as exc:
            logger.warning("Wake greeting failed for %s: %s", agent.name, exc)

    async def _trigger_pre_market(self, agent) -> dict | None:
        """Send the morning_research task to the agent.

        P10 + P9: if the agent has no running session, auto-start one first, then
        push a trigger through the Redis trigger bus so the agent actually wakes.
        """
        try:
            from apps.api.src.services.agent_gateway import gateway, _running_tasks

            agent_key = str(agent.id)
            started_fresh = False
            if agent_key not in _running_tasks or _running_tasks[agent_key].done():
                # Auto-start agent session. create_analyst signature is (agent_id, config)
                # — no `resume` kwarg, so pass nothing extra.
                try:
                    spawn_result = await gateway.create_analyst(agent.id)
                    if not spawn_result or (
                        isinstance(spawn_result, str)
                        and (spawn_result.startswith("BUDGET_EXCEEDED")
                             or spawn_result.startswith("NOT_ELIGIBLE"))
                    ):
                        logger.warning(
                            "[morning] create_analyst rejected %s (status=%s, result=%r)",
                            agent.name, agent.status, spawn_result,
                        )
                        return None
                    started_fresh = True
                except Exception as e:
                    logger.warning("Auto-start failed for %s: %s", agent.name, e)
                    return None

            prompt = (
                "MORNING_RESEARCH: Run your pre-market analysis routine. "
                "Steps: "
                "1) Run `python tools/pre_market_analyzer.py --config config.json --output market_context.json` "
                "2) Read market_context.json and extract key findings "
                "3) Broadcast findings: `python tools/agent_comms.py --broadcast --intent morning_research --data market_context.json` "
                "4) Check peer messages: `python tools/agent_comms.py --get-pending` "
                "5) Send a brief summary to Phoenix via report_to_phoenix.py with event_type=morning_briefing_complete"
            )

            result = await gateway.send_task(agent.id, prompt)
            # Always publish via trigger bus so the agent's consumer loop picks it up
            try:
                await gateway.dispatch_trigger(
                    agent.id,
                    "cron:morning_briefing",
                    {"prompt": prompt, "auto_started": started_fresh},
                )
            except Exception:
                pass
            if isinstance(result, dict):
                result["auto_started"] = started_fresh
            return result
        except Exception as exc:
            logger.error("Pre-market trigger failed for %s: %s", agent.name, exc)
            return None

    def _compile_briefing(self, summaries: list[dict]) -> str:
        now = datetime.now(timezone.utc)
        lines = [
            f"Morning Market Briefing — {now.strftime('%B %d, %Y')}",
            f"Active agents: {len(summaries)}",
            "",
        ]
        for s in summaries:
            lines.append(
                f"• {s['name']} ({s.get('channel', '?')}) — character: {s.get('character', '?')}"
            )
        lines.extend([
            "",
            "Each agent is now running pre-market analysis and sharing findings with peers.",
            "Trade signals will be sent as they occur.",
        ])
        return "\n".join(lines)

    async def _dispatch_briefing(self, briefing: str) -> None:
        try:
            from apps.api.src.services.notification_dispatcher import notification_dispatcher
            await notification_dispatcher.dispatch(
                event_type="morning_briefing",
                agent_id=None,
                title="Morning Market Briefing",
                body=briefing,
                channels=["whatsapp", "ws", "db"],
            )
        except Exception as exc:
            logger.error("Briefing dispatch failed: %s", exc)


# Module-level singleton
morning_routine = MorningRoutineOrchestrator()

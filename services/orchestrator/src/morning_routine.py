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
            "agents_woken": 0,
            "agents_triggered": 0,
            "briefing_sent": False,
            "errors": [],
        }

        agents: list = []
        async for session in get_session():
            query = select(Agent).where(Agent.status.in_(["RUNNING", "PAPER", "APPROVED"]))
            rows = await session.execute(query)
            agents = list(rows.scalars().all())

        if not agents:
            results["message"] = "No active agents found"
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
        """Send the morning_research task to the agent via send_task."""
        try:
            from apps.api.src.services.agent_gateway import gateway

            prompt = (
                "MORNING_RESEARCH: Run your pre-market analysis routine. "
                "Steps: "
                "1) Run `python tools/pre_market_analyzer.py --config config.json --output market_context.json` "
                "2) Read market_context.json and extract key findings "
                "3) Broadcast findings: `python tools/agent_comms.py --broadcast --intent morning_research --data market_context.json` "
                "4) Check peer messages: `python tools/agent_comms.py --get-pending` "
                "5) Send a brief summary to Phoenix via report_to_phoenix.py with event_type=morning_briefing_complete"
            )

            return await gateway.send_task(agent.id, prompt)
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

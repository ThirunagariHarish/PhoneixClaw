"""
Automation Scheduler Service — cron-based task scheduling with NL-to-cron conversion.

M3.5: Automations.
Reference: PRD Section 3.10, ImplementationPlan Section 10.5.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any

from croniter import croniter

logger = logging.getLogger(__name__)

NL_CRON_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r"every\s+morning\s+at\s+(\d{1,2})\s*(am|pm)?", re.I), "0 {hour} * * *"),
    (re.compile(r"every\s+(\d{1,2})\s+minutes?", re.I), "*/{n} * * * *"),
    (re.compile(r"every\s+(\d{1,2})\s+hours?", re.I), "0 */{n} * * *"),
    (re.compile(r"every\s+hour\s+during\s+market\s+hours", re.I), "0 * 9-16 * * 1-5"),
    (re.compile(r"every\s+friday\s+before\s+market\s+close", re.I), "0 15 * * 5"),
    (re.compile(r"daily\s+at\s+(\d{1,2})\s*(am|pm)?", re.I), "0 {hour} * * *"),
    (re.compile(r"every\s+weekday\s+at\s+(\d{1,2})\s*(am|pm)?", re.I), "0 {hour} * * 1-5"),
]


def nl_to_cron(text: str) -> str | None:
    """Convert natural language schedule description to a cron expression."""
    text = text.strip()
    for pattern, template in NL_CRON_MAP:
        m = pattern.search(text)
        if m:
            groups = m.groups()
            if "{hour}" in template:
                hour = int(groups[0])
                meridiem = groups[1] if len(groups) > 1 else None
                if meridiem and meridiem.lower() == "pm" and hour < 12:
                    hour += 12
                return template.replace("{hour}", str(hour))
            if "{n}" in template:
                return template.replace("{n}", groups[0])
            return template
    return None


def validate_cron(expression: str) -> bool:
    """Return True if `expression` is a valid cron expression."""
    try:
        croniter(expression)
        return True
    except (ValueError, KeyError):
        return False


def next_run_time(expression: str, base: datetime | None = None) -> datetime:
    """Compute the next execution time for a cron expression."""
    base = base or datetime.now(timezone.utc)
    return croniter(expression, base).get_next(datetime)


AUTOMATION_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "morning-briefing",
        "name": "Morning Market Briefing",
        "description": "Daily pre-market summary of indices, key movers, and overnight news.",
        "cron_expression": "0 8 * * 1-5",
        "agent_role": "Market Research Analyst",
        "delivery_channel": "telegram",
    },
    {
        "id": "eod-summary",
        "name": "EOD Portfolio Summary",
        "description": "End-of-day portfolio performance, positions, and P&L.",
        "cron_expression": "0 16 * * 1-5",
        "agent_role": "Report Generator",
        "delivery_channel": "dashboard",
    },
    {
        "id": "weekly-report",
        "name": "Weekly Performance Report",
        "description": "Comprehensive weekly trading performance analysis.",
        "cron_expression": "0 17 * * 5",
        "agent_role": "Report Generator",
        "delivery_channel": "discord",
    },
    {
        "id": "earnings-preview",
        "name": "Earnings Preview",
        "description": "Pre-earnings analysis for watchlist tickers.",
        "cron_expression": "0 20 * * 1-5",
        "agent_role": "Technical Analysis Expert",
        "delivery_channel": "telegram",
    },
    {
        "id": "options-expiry",
        "name": "Options Expiration Alert",
        "description": "Weekly options expiration positions and roll suggestions.",
        "cron_expression": "0 10 * * 5",
        "agent_role": "Options Specialist",
        "delivery_channel": "dashboard",
    },
    {
        "id": "risk-assessment",
        "name": "Risk Assessment",
        "description": "Periodic portfolio risk assessment during market hours.",
        "cron_expression": "0 */4 9-16 * * 1-5",
        "agent_role": "Risk Analyzer",
        "delivery_channel": "dashboard",
    },
]


class AutomationScheduler:
    """
    Manages cron-scheduled automations. Runs an asyncio loop that checks
    pending automations each minute and dispatches tasks.
    """

    def __init__(self, task_creator=None, delivery_router=None):
        self._task_creator = task_creator
        self._delivery_router = delivery_router
        self._running = False
        self._automations: dict[str, dict] = {}

    def register(self, automation_id: str, cron_expression: str, config: dict):
        if not validate_cron(cron_expression):
            raise ValueError(f"Invalid cron expression: {cron_expression}")
        self._automations[automation_id] = {
            "cron": cron_expression,
            "config": config,
            "next_run": next_run_time(cron_expression),
        }
        logger.info("Registered automation %s with cron '%s'", automation_id, cron_expression)

    def unregister(self, automation_id: str):
        self._automations.pop(automation_id, None)
        logger.info("Unregistered automation %s", automation_id)

    async def start(self):
        self._running = True
        logger.info("Automation scheduler started with %d automations", len(self._automations))
        while self._running:
            now = datetime.now(timezone.utc)
            for auto_id, entry in list(self._automations.items()):
                if now >= entry["next_run"]:
                    await self._execute(auto_id, entry)
                    entry["next_run"] = next_run_time(entry["cron"], now)
            await asyncio.sleep(30)

    def stop(self):
        self._running = False

    async def _execute(self, automation_id: str, entry: dict):
        config = entry["config"]
        logger.info("Executing automation %s", automation_id)
        try:
            if self._task_creator:
                task = await self._task_creator(
                    title=config.get("name", automation_id),
                    agent_role=config.get("agent_role", "Report Generator"),
                    description=config.get("description", ""),
                    automation_id=automation_id,
                )
                if self._delivery_router and task:
                    await self._delivery_router(
                        channel=config.get("delivery_channel", "dashboard"),
                        payload=task,
                        config=config.get("delivery_config", {}),
                    )
        except Exception:
            logger.exception("Automation %s failed", automation_id)

    @staticmethod
    def get_templates() -> list[dict[str, Any]]:
        return AUTOMATION_TEMPLATES

    @staticmethod
    def idempotency_key(automation_id: str, run_time: datetime) -> str:
        raw = f"{automation_id}:{run_time.isoformat()}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

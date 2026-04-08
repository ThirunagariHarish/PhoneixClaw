"""
Skill distributor — pushes skill files to OpenClaw instances
via the Bridge API.

M2.9: Skill distribution pipeline.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DistributionStatus:
    instance_id: str
    url: str
    success: bool
    status_code: int = 0
    error: str = ""
    timestamp: str = ""


class SkillDistributor:
    """Uploads skill files to OpenClaw instances via Bridge API."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._history: list[DistributionStatus] = []

    async def distribute(
        self, skill_path: str, instances: list[dict[str, Any]]
    ) -> list[DistributionStatus]:
        """Distribute a skill file to all provided instances.

        Each instance dict must contain ``id`` and ``url`` keys.
        The skill is POSTed to ``{url}/skills/sync``.
        """
        path = Path(skill_path)
        if not path.exists():
            logger.error("Skill file not found: %s", skill_path)
            return []

        content = path.read_text()
        skill_name = path.stem
        results: list[DistributionStatus] = []

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for inst in instances:
                inst_id = inst["id"]
                base_url = inst["url"].rstrip("/")
                status = await self._send(client, inst_id, base_url, skill_name, content)
                results.append(status)
                self._history.append(status)

        succeeded = sum(1 for r in results if r.success)
        logger.info(
            "Distributed %s to %d/%d instances", skill_name, succeeded, len(instances)
        )
        return results

    async def _send(
        self,
        client: httpx.AsyncClient,
        inst_id: str,
        base_url: str,
        skill_name: str,
        content: str,
    ) -> DistributionStatus:
        url = f"{base_url}/skills/sync"
        now = datetime.now(timezone.utc).isoformat()
        try:
            resp = await client.post(
                url,
                json={"skill_name": skill_name, "content": content},
            )
            success = 200 <= resp.status_code < 300
            if not success:
                logger.warning("Instance %s returned %d", inst_id, resp.status_code)
            return DistributionStatus(
                instance_id=inst_id, url=url, success=success,
                status_code=resp.status_code, timestamp=now,
            )
        except httpx.HTTPError as exc:
            logger.error("Failed to reach instance %s: %s", inst_id, exc)
            return DistributionStatus(
                instance_id=inst_id, url=url, success=False,
                error=str(exc), timestamp=now,
            )

    @property
    def history(self) -> list[DistributionStatus]:
        return list(self._history)

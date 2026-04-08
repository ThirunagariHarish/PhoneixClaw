"""
Skill Sync Service — distributes skills from central repo to OpenClaw instances.

M2.2: Skill distribution across all instances.
Reference: PRD Section 12.7, ArchitecturePlan §6.
"""

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class SkillSyncService:
    """
    Manages skill distribution from the central skill repository (MinIO/local)
    to all registered OpenClaw instances via their Bridge Service API.
    """

    def __init__(self, skills_dir: str = "openclaw/skills", bridge_instances: list[dict] | None = None):
        self.skills_dir = Path(skills_dir)
        self.bridge_instances = bridge_instances or []
        self._version_cache: dict[str, str] = {}

    def scan_skills(self) -> list[dict[str, Any]]:
        """Scan local skill directory and return skill metadata."""
        skills = []
        for category_dir in sorted(self.skills_dir.iterdir()):
            if not category_dir.is_dir() or category_dir.name.startswith("."):
                continue
            category = category_dir.name
            for skill_file in sorted(category_dir.glob("*.md")):
                content = skill_file.read_text(encoding="utf-8")
                skill_id = f"{category}/{skill_file.stem}"
                content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
                skills.append({
                    "id": skill_id,
                    "category": category,
                    "name": skill_file.stem,
                    "file": str(skill_file),
                    "hash": content_hash,
                    "size_bytes": len(content.encode()),
                })
        return skills

    async def sync_to_instance(self, instance: dict, skills: list[dict]) -> dict[str, Any]:
        """Push skills to a single OpenClaw instance via its Bridge API."""
        bridge_url = f"http://{instance['host']}:{instance['port']}"
        token = instance.get("bridge_token", "")
        results = {"instance": instance["name"], "synced": 0, "skipped": 0, "errors": 0}

        async with httpx.AsyncClient(timeout=30.0) as client:
            for skill in skills:
                try:
                    resp = await client.post(
                        f"{bridge_url}/skills/sync",
                        json={"skill_id": skill["id"], "hash": skill["hash"]},
                        headers={"X-Bridge-Token": token},
                    )
                    if resp.status_code == 200:
                        results["synced"] += 1
                    else:
                        results["skipped"] += 1
                except Exception as e:
                    logger.error("Failed to sync skill %s to %s: %s", skill["id"], instance["name"], e)
                    results["errors"] += 1

        return results

    async def sync_all(self) -> dict[str, Any]:
        """Sync all skills to all registered instances."""
        skills = self.scan_skills()
        logger.info("Found %d skills to sync", len(skills))

        results = []
        for instance in self.bridge_instances:
            result = await self.sync_to_instance(instance, skills)
            results.append(result)

        return {
            "total_skills": len(skills),
            "instances_synced": len(results),
            "results": results,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

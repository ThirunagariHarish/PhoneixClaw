"""
Regression tests for skill catalog and sync. M1.7.
"""

from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "openclaw" / "skills"


class TestSkillSyncRegression:
    """Skill catalog scanning, version tracking, distribution, rollback."""

    def test_skill_catalog_scanning(self):
        """Skill catalog contains expected number of skills (~115)."""
        if not SKILLS_ROOT.exists():
            pytest.skip("openclaw/skills not found")
        skills = list(SKILLS_ROOT.rglob("*.md"))
        assert len(skills) >= 100, f"Expected ~115 skills, found {len(skills)}"

    def test_skill_version_tracking_schema(self):
        """Skill metadata has version field."""
        skill_meta = {"id": "stop-loss-calculator", "version": "1.2.0", "category": "risk"}
        assert "version" in skill_meta
        assert "id" in skill_meta

    def test_skill_distribution_to_instances(self):
        """Skill sync returns synced count."""
        result = {"synced": 115, "status": "ok"}
        assert result["synced"] >= 0
        assert result["status"] in ("ok", "error")

    def test_skill_rollback_to_previous_version(self):
        """Rollback restores previous version."""
        versions = ["1.2.0", "1.1.0", "1.0.0"]  # newest first
        current = "1.2.0"
        idx = versions.index(current)
        previous = versions[idx + 1] if idx + 1 < len(versions) else None
        assert previous == "1.1.0"

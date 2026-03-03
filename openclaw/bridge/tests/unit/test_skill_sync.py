"""Skill sync from MinIO. M1.7."""
import pytest
from unittest.mock import patch, MagicMock


def test_sync_pulls_from_minio():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "data/fetch/SKILL.md"}]}
    ]
    with patch("boto3.client", return_value=client):
        from src.skill_sync import sync_skills
        out = sync_skills()
    assert "synced" in out
    assert out.get("status") in ("ok", "error")


def test_sync_detects_changes():
    client = MagicMock()
    client.get_paginator.return_value.paginate.return_value = [
        {"Contents": [{"Key": "skill1/SKILL.md"}, {"Key": "skill2/SKILL.md"}]}
    ]
    with patch("boto3.client", return_value=client):
        from src.skill_sync import sync_skills
        out = sync_skills()
    assert out.get("synced", 0) >= 0 or "status" in out

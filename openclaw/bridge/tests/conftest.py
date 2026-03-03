"""Pytest fixtures. Set AGENTS_ROOT to temp for agent_manager tests."""
import pytest


@pytest.fixture(autouse=True)
def bridge_env(monkeypatch, tmp_path):
    """Use temp dir for AGENTS_ROOT when running in tests."""
    monkeypatch.setenv("AGENTS_ROOT", str(tmp_path))

"""Smoke test for Loki retention configuration in docker-compose.yml.

Verifies that the Loki service has retention settings configured correctly.
"""

import re

import pytest
import yaml


@pytest.fixture
def docker_compose_config():
    """Load docker-compose.yml."""
    with open("docker-compose.yml") as f:
        return yaml.safe_load(f)


def test_loki_service_exists(docker_compose_config):
    """Loki service should be defined."""
    assert "loki" in docker_compose_config["services"], "Loki service not found in docker-compose.yml"


def test_loki_retention_configured(docker_compose_config):
    """Loki should have 30-day retention configured."""
    loki_service = docker_compose_config["services"]["loki"]

    # Check command field exists and has retention config
    assert "command" in loki_service, "Loki service missing command field"

    command = loki_service["command"]
    # Command can be string or list
    if isinstance(command, list):
        command_str = " ".join(command)
    else:
        command_str = command

    # Verify retention settings
    assert "retention-period=720h" in command_str or "retention.period=720h" in command_str, (
        "Loki retention period not set to 720h (30 days)"
    )

    # Verify retention deletes are enabled
    assert "retention-deletes-enabled=true" in command_str or "retention_deletes_enabled=true" in command_str, (
        "Loki retention deletes not enabled"
    )


def test_loki_has_volume(docker_compose_config):
    """Loki should have persistent volume for data."""
    loki_service = docker_compose_config["services"]["loki"]
    assert "volumes" in loki_service, "Loki service missing volumes"
    assert any("loki" in vol for vol in loki_service["volumes"]), "Loki service missing loki data volume"


def test_loki_port_exposed(docker_compose_config):
    """Loki should expose port 3100."""
    loki_service = docker_compose_config["services"]["loki"]
    assert "ports" in loki_service, "Loki service missing ports"
    ports = loki_service["ports"]

    # Check for 3100 port mapping (can be "3100:3100" or list)
    port_found = False
    for port_mapping in ports:
        if isinstance(port_mapping, str):
            if "3100" in port_mapping:
                port_found = True
                break
        elif isinstance(port_mapping, dict):
            if port_mapping.get("published") == 3100 or port_mapping.get("target") == 3100:
                port_found = True
                break

    assert port_found, "Loki port 3100 not exposed"


def test_retention_period_is_30_days(docker_compose_config):
    """Retention period should be exactly 720h (30 days)."""
    loki_service = docker_compose_config["services"]["loki"]
    command = loki_service["command"]

    if isinstance(command, list):
        command_str = " ".join(command)
    else:
        command_str = command

    # Extract retention period value
    match = re.search(r"retention[_-]period=(\d+h)", command_str)
    assert match, "Could not find retention-period setting in Loki command"

    retention_value = match.group(1)
    assert retention_value == "720h", f"Retention period is {retention_value}, expected 720h"

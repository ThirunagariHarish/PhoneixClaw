"""
Unit tests for agents_sprint.py self-heal functionality.

These tests verify that the /channel-messages endpoint correctly:
1. Self-heals missing ConnectorAgent rows from agent.config.connector_ids
2. Returns has_connectors: False when agent has no connectors in config
3. Returns has_connectors: True when agent has connectors (after self-heal)
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_self_heal_creates_missing_connector_agent_rows():
    """When agent has connector_ids in config but no ConnectorAgent rows,
    the endpoint should create them and return has_connectors: True."""
    from apps.api.src.routes.agents_sprint import get_channel_messages

    agent_id = uuid.uuid4()
    connector_id = uuid.uuid4()

    # Mock session that returns:
    # 1. Empty ConnectorAgent query (no rows)
    # 2. Agent with connector_ids in config
    # 3. Empty existing ConnectorAgent check (so it creates new row)
    # 4. Empty ChannelMessage query
    mock_session = AsyncMock()

    # First execute: ConnectorAgent query returns empty
    connector_agent_result = MagicMock()
    connector_agent_result.all.return_value = []

    # Second execute: Agent query returns agent with connector_ids in config
    agent_mock = MagicMock()
    agent_mock.id = agent_id
    agent_mock.config = {"connector_ids": [str(connector_id)]}
    agent_result = MagicMock()
    agent_result.scalar_one_or_none.return_value = agent_mock

    # Third execute: existing ConnectorAgent check returns None
    existing_ca_result = MagicMock()
    existing_ca_result.scalar_one_or_none.return_value = None

    # Fourth execute: ChannelMessage query returns empty
    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [
        connector_agent_result,
        agent_result,
        existing_ca_result,
        messages_result,
    ]

    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()

    result = await get_channel_messages(
        agent_id=agent_id, limit=200, since=None, session=mock_session
    )

    # Should have called session.add to create ConnectorAgent row
    assert mock_session.add.called, "Expected session.add to be called"
    # Should have committed the new row
    assert mock_session.commit.called, "Expected session.commit to be called"
    # Should return has_connectors: True
    assert result["has_connectors"] is True
    assert result["messages"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_no_self_heal_when_agent_has_no_connector_ids():
    """When agent has no connector_ids in config, should return has_connectors: False."""
    from apps.api.src.routes.agents_sprint import get_channel_messages

    agent_id = uuid.uuid4()

    mock_session = AsyncMock()

    # First execute: ConnectorAgent query returns empty
    connector_agent_result = MagicMock()
    connector_agent_result.all.return_value = []

    # Second execute: Agent query returns agent with empty connector_ids
    agent_mock = MagicMock()
    agent_mock.id = agent_id
    agent_mock.config = {}  # No connector_ids
    agent_result = MagicMock()
    agent_result.scalar_one_or_none.return_value = agent_mock

    mock_session.execute.side_effect = [
        connector_agent_result,
        agent_result,
    ]

    result = await get_channel_messages(
        agent_id=agent_id, limit=200, since=None, session=mock_session
    )

    # Should NOT have called session.add or commit
    assert not hasattr(
        mock_session, "add"
    ), "session.add should not be called when no connector_ids"
    # Should return has_connectors: False
    assert result["has_connectors"] is False
    assert result["messages"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_no_self_heal_when_connector_agent_rows_exist():
    """When ConnectorAgent rows already exist, should not trigger self-heal."""
    from apps.api.src.routes.agents_sprint import get_channel_messages

    agent_id = uuid.uuid4()
    connector_id = uuid.uuid4()

    mock_session = AsyncMock()

    # First execute: ConnectorAgent query returns existing row
    ca_row = (connector_id,)
    connector_agent_result = MagicMock()
    connector_agent_result.all.return_value = [ca_row]

    # Second execute: ChannelMessage query returns empty
    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [
        connector_agent_result,
        messages_result,
    ]

    result = await get_channel_messages(
        agent_id=agent_id, limit=200, since=None, session=mock_session
    )

    # Should return has_connectors: True (connector already linked)
    assert result["has_connectors"] is True
    assert result["messages"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_self_heal_handles_invalid_connector_id_gracefully():
    """When agent.config has invalid connector_id, should log warning and continue."""
    from apps.api.src.routes.agents_sprint import get_channel_messages

    agent_id = uuid.uuid4()

    mock_session = AsyncMock()

    # First execute: ConnectorAgent query returns empty
    connector_agent_result = MagicMock()
    connector_agent_result.all.return_value = []

    # Second execute: Agent query returns agent with invalid connector_id
    agent_mock = MagicMock()
    agent_mock.id = agent_id
    agent_mock.config = {"connector_ids": ["not-a-valid-uuid", None, ""]}
    agent_result = MagicMock()
    agent_result.scalar_one_or_none.return_value = agent_mock

    mock_session.execute.side_effect = [
        connector_agent_result,
        agent_result,
    ]

    with patch("apps.api.src.routes.agents_sprint.logger") as mock_logger:
        result = await get_channel_messages(
            agent_id=agent_id, limit=200, since=None, session=mock_session
        )

        # Should have logged warning about invalid connector_id
        assert mock_logger.warning.called, "Expected warning to be logged for invalid UUID"

    # Should return has_connectors: False (no valid connectors)
    assert result["has_connectors"] is False
    assert result["messages"] == []
    assert result["count"] == 0


@pytest.mark.asyncio
async def test_self_heal_rollback_on_commit_failure():
    """When commit fails during self-heal, should rollback and log warning."""
    from apps.api.src.routes.agents_sprint import get_channel_messages

    agent_id = uuid.uuid4()
    connector_id = uuid.uuid4()

    mock_session = AsyncMock()

    # First execute: ConnectorAgent query returns empty
    connector_agent_result = MagicMock()
    connector_agent_result.all.return_value = []

    # Second execute: Agent query returns agent with connector_ids
    agent_mock = MagicMock()
    agent_mock.id = agent_id
    agent_mock.config = {"connector_ids": [str(connector_id)]}
    agent_result = MagicMock()
    agent_result.scalar_one_or_none.return_value = agent_mock

    # Third execute: existing ConnectorAgent check returns None
    existing_ca_result = MagicMock()
    existing_ca_result.scalar_one_or_none.return_value = None

    # Fourth execute: ChannelMessage query returns empty
    messages_result = MagicMock()
    messages_result.scalars.return_value.all.return_value = []

    mock_session.execute.side_effect = [
        connector_agent_result,
        agent_result,
        existing_ca_result,
        messages_result,
    ]

    mock_session.add = MagicMock()
    # Make commit raise an exception
    mock_session.commit = AsyncMock(side_effect=Exception("DB error"))
    mock_session.rollback = AsyncMock()

    with patch("apps.api.src.routes.agents_sprint.logger") as mock_logger:
        result = await get_channel_messages(
            agent_id=agent_id, limit=200, since=None, session=mock_session
        )

        # Should have called rollback
        assert mock_session.rollback.called, "Expected rollback on commit failure"
        # Should have logged warning
        assert mock_logger.warning.called, "Expected warning on commit failure"

    # Should still return has_connectors: True (connector was found in config)
    assert result["has_connectors"] is True
    assert result["messages"] == []
    assert result["count"] == 0

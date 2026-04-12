"""Trading agent create: connector_ids required when a Discord channel is selected."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from apps.api.src.routes.agents import AgentCreate, assert_trading_connector_when_discord_channel


def test_trading_no_selected_channel_ok():
    assert_trading_connector_when_discord_channel(
        AgentCreate(name="a", type="trading", config={}, connector_ids=[])
    )


def test_trading_selected_channel_without_id_ok():
    assert_trading_connector_when_discord_channel(
        AgentCreate(
            name="a",
            type="trading",
            config={"selected_channel": {"channel_name": "general"}},
            connector_ids=[],
        )
    )


def test_trading_selected_channel_requires_connector():
    with pytest.raises(HTTPException) as exc:
        assert_trading_connector_when_discord_channel(
            AgentCreate(
                name="a",
                type="trading",
                config={"selected_channel": {"channel_id": "1234567890"}},
                connector_ids=[],
            )
        )
    assert exc.value.status_code == 400
    assert "connector" in exc.value.detail.lower()


def test_non_trading_type_skips_check():
    assert_trading_connector_when_discord_channel(
        AgentCreate(
            name="a",
            type="trend",
            config={"selected_channel": {"channel_id": "1234567890"}},
            connector_ids=[],
        )
    )


def test_trading_with_channel_and_connector_ok():
    cid = str(uuid.uuid4())
    assert_trading_connector_when_discord_channel(
        AgentCreate(
            name="a",
            type="trading",
            config={"selected_channel": {"channel_id": "1234567890"}},
            connector_ids=[cid],
        )
    )

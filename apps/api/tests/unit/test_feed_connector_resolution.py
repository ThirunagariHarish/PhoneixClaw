"""Unit tests for Feed connector ID parsing (no DB)."""

from __future__ import annotations

import uuid

from apps.api.src.services.feed_connector_resolution import (
    discord_channel_ids_from_config,
    parse_connector_ids_from_config,
)

# ---------------------------------------------------------------------------
# parse_connector_ids_from_config
# ---------------------------------------------------------------------------

def test_parse_empty_config():
    assert parse_connector_ids_from_config(None) == set()
    assert parse_connector_ids_from_config({}) == set()


def test_parse_skips_invalid_entries():
    u = uuid.uuid4()
    got = parse_connector_ids_from_config(
        {"connector_ids": ["not-a-uuid", str(u), 123, None, u]}
    )
    assert got == {u}


def test_parse_ignores_non_list():
    assert parse_connector_ids_from_config({"connector_ids": "x"}) == set()


# ---------------------------------------------------------------------------
# discord_channel_ids_from_config
# ---------------------------------------------------------------------------

def test_channel_ids_from_channel_ids_key():
    cfg = {"channel_ids": ["111", "222"]}
    assert discord_channel_ids_from_config(cfg) == ["111", "222"]


def test_channel_ids_from_channel_id_singular():
    cfg = {"channel_id": "999"}
    assert discord_channel_ids_from_config(cfg) == ["999"]


def test_channel_ids_from_selected_channels_dicts():
    cfg = {
        "selected_channels": [
            {"channel_id": "100", "channel_name": "general"},
            {"channel_id": "200", "channel_name": "day-trades"},
        ]
    }
    assert discord_channel_ids_from_config(cfg) == ["100", "200"]


def test_channel_ids_from_selected_channels_strings():
    cfg = {"selected_channels": ["100", "200"]}
    assert discord_channel_ids_from_config(cfg) == ["100", "200"]


def test_channel_ids_prefers_channel_ids_over_selected_channels():
    cfg = {"channel_ids": ["111"], "selected_channels": [{"channel_id": "999"}]}
    assert discord_channel_ids_from_config(cfg) == ["111"]


def test_channel_ids_empty_config():
    assert discord_channel_ids_from_config(None) == []
    assert discord_channel_ids_from_config({}) == []


def test_channel_ids_skips_empty_entries():
    cfg = {"selected_channels": [{"channel_name": "no-id"}, {"channel_id": ""}, {"channel_id": "123"}]}
    assert discord_channel_ids_from_config(cfg) == ["123"]

"""Unit tests for Feed connector ID parsing (no DB)."""

from __future__ import annotations

import uuid

import pytest

from apps.api.src.services.feed_connector_resolution import parse_connector_ids_from_config


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

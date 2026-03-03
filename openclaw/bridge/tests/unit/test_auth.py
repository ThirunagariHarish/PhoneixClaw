"""X-Bridge-Token auth. M1.7."""
import pytest
from fastapi import HTTPException
from src.auth import validate_bridge_token


def test_valid_token_passes(monkeypatch):
    monkeypatch.setattr("src.auth.settings", type("S", (), {"BRIDGE_TOKEN": "secret"})())
    assert validate_bridge_token("secret") == "secret"


def test_invalid_token_returns_401(monkeypatch):
    monkeypatch.setattr("src.auth.settings", type("S", (), {"BRIDGE_TOKEN": "secret"})())
    with pytest.raises(HTTPException) as exc:
        validate_bridge_token("wrong")
    assert exc.value.status_code == 401


def test_missing_token_returns_401(monkeypatch):
    monkeypatch.setattr("src.auth.settings", type("S", (), {"BRIDGE_TOKEN": "secret"})())
    with pytest.raises(HTTPException) as exc:
        validate_bridge_token("")
    assert exc.value.status_code == 401

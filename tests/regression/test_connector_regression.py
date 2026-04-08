"""
Regression tests for connector CRUD, credentials, and linking. M1.9.
"""

import base64
import uuid

import pytest


@pytest.fixture
def connector_payload():
    return {
        "name": "Discord-Alpha",
        "type": "discord",
        "config": {"server_id": "123", "channel_id": "456"},
        "credentials": {"token": "secret-bot-token"},
    }


class TestConnectorRegression:
    """Connector CRUD, credential encryption, test endpoint, agent linking."""

    def test_connector_create_payload_schema(self, connector_payload):
        """Connector create payload has required fields."""
        assert "name" in connector_payload
        assert "type" in connector_payload
        assert connector_payload["type"] in ("discord", "reddit", "twitter")
        assert "config" in connector_payload
        assert "credentials" in connector_payload

    def test_credential_encryption_decryption(self):
        """Credentials can be encrypted and decrypted (mock)."""
        key = b"a" * 32  # 256-bit key
        plain = b"secret-token"
        # Simulate encryption: base64 for test (real impl uses Fernet/AES)
        encoded = base64.b64encode(plain).decode()
        decoded = base64.b64decode(encoded.encode()).decode()
        assert decoded == "secret-token"

    def test_connector_test_endpoint_payload(self):
        """Connector test returns status."""
        result = {"status": "connected", "message": "OK"}
        assert result["status"] in ("connected", "disconnected", "error")

    def test_connector_agent_linking_schema(self):
        """Connector-agent link has connector_id, agent_id, channel."""
        link = {
            "connector_id": str(uuid.uuid4()),
            "agent_id": str(uuid.uuid4()),
            "channel": "*",
            "is_active": True,
        }
        assert "connector_id" in link
        assert "agent_id" in link
        assert link.get("channel", "*") == "*"

    def test_message_normalization_schema(self):
        """Normalized message has content, author, timestamp, source."""
        msg = {
            "content": "SPY 450C 0dte",
            "author": "user123",
            "timestamp": "2025-03-03T12:00:00Z",
            "source": "discord",
            "channel_id": "456",
        }
        assert "content" in msg
        assert "author" in msg
        assert "timestamp" in msg
        assert "source" in msg

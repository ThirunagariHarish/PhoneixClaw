
import pytest
from cryptography.fernet import Fernet

from shared.broker.factory import create_broker_adapter


@pytest.fixture(autouse=True)
def setup_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("CREDENTIAL_ENCRYPTION_KEY", key)
    import importlib

    import shared.config.base_config
    import shared.crypto.credentials
    importlib.reload(shared.config.base_config)
    importlib.reload(shared.crypto.credentials)


class TestBrokerFactory:
    def test_creates_alpaca_adapter(self):
        from shared.crypto.credentials import encrypt_credentials
        creds = encrypt_credentials({"api_key": "test-key", "secret_key": "test-secret"})
        adapter = create_broker_adapter("alpaca", creds, paper_mode=True)
        assert adapter is not None

    def test_unsupported_broker_raises(self):
        from shared.crypto.credentials import encrypt_credentials
        creds = encrypt_credentials({"key": "value"})
        with pytest.raises(ValueError, match="Unsupported broker"):
            create_broker_adapter("unknown_broker", creds)

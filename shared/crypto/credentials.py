"""Fernet-based credential encryption utilities."""
import json
import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("FERNET_KEY") or os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError(
            "FERNET_KEY or CREDENTIAL_ENCRYPTION_KEY environment variable is required"
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_value(plaintext: str) -> str:
    return _get_fernet().encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    return _get_fernet().decrypt(ciphertext.encode()).decode()


def encrypt_credentials(creds: dict) -> str:
    return encrypt_value(json.dumps(creds))


def decrypt_credentials(encrypted: str) -> dict:
    return json.loads(decrypt_value(encrypted))

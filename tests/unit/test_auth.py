import pytest
from jose import jwt
from services.auth_service.src.auth import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)

from shared.config.base_config import config


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "s3cureP@ss!"
        hashed = hash_password(pw)
        assert hashed != pw
        assert verify_password(pw, hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("correct")
        assert not verify_password("wrong", hashed)

    def test_different_hashes_for_same_password(self):
        h1 = hash_password("test")
        h2 = hash_password("test")
        assert h1 != h2  # bcrypt salt


class TestTokenCreation:
    def test_access_token_contains_sub(self):
        token = create_access_token("user-123")
        payload = jwt.decode(token, config.auth.secret_key, algorithms=[config.auth.algorithm])
        assert payload["sub"] == "user-123"
        assert payload["type"] == "access"

    def test_refresh_token_contains_sub(self):
        token = create_refresh_token("user-456")
        payload = jwt.decode(token, config.auth.secret_key, algorithms=[config.auth.algorithm])
        assert payload["sub"] == "user-456"
        assert payload["type"] == "refresh"

    def test_tokens_have_expiry(self):
        token = create_access_token("user-1")
        payload = jwt.decode(token, config.auth.secret_key, algorithms=[config.auth.algorithm])
        assert "exp" in payload

    def test_decode_valid_token(self):
        token = create_access_token("user-x")
        payload = decode_token(token)
        assert payload["sub"] == "user-x"

    def test_decode_invalid_token_raises(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            decode_token("invalid.token.here")

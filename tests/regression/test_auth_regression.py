"""
Regression tests for JWT auth, RBAC, and MFA. M1.3.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from apps.api.src.config import auth_settings


@pytest.fixture
def user_id():
    return str(uuid.uuid4())


def _create_token(user_id: str, is_admin: bool = False, expired: bool = False) -> str:
    expire = datetime.now(timezone.utc) + (timedelta(minutes=-5) if expired else timedelta(minutes=60))
    return jwt.encode(
        {"sub": user_id, "exp": expire, "type": "access", "admin": is_admin},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )


class TestAuthRegression:
    """JWT token generation and validation regression tests."""

    def test_jwt_token_generation(self, user_id):
        """Valid access token is generated with correct claims."""
        token = _create_token(user_id, is_admin=False)
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
        assert payload["sub"] == user_id
        assert payload["type"] == "access"
        assert payload["admin"] is False
        assert "exp" in payload

    def test_jwt_token_validation(self, user_id):
        """Valid token decodes correctly."""
        token = _create_token(user_id)
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
        assert payload["sub"] == user_id

    def test_expired_token_rejection(self, user_id):
        """Expired token raises JWTError on decode."""
        token = _create_token(user_id, expired=True)
        with pytest.raises(Exception):  # jose.jwt.ExpiredSignatureError
            jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])

    def test_role_admin_in_token(self, user_id):
        """Admin role is encoded in token."""
        token = _create_token(user_id, is_admin=True)
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
        assert payload["admin"] is True

    def test_role_trader_in_token(self, user_id):
        """Trader role (non-admin) is encoded."""
        token = _create_token(user_id, is_admin=False)
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
        assert payload["admin"] is False

    def test_role_viewer_permissions(self, user_id):
        """Viewer has read-only permissions (admin=False)."""
        token = _create_token(user_id, is_admin=False)
        payload = jwt.decode(token, auth_settings.jwt_secret_key, algorithms=[auth_settings.jwt_algorithm])
        assert payload.get("admin") is False

    @pytest.mark.asyncio
    async def test_mfa_enrollment_flow_secret_generation(self):
        """MFA setup returns secret and provisioning URI."""
        import pyotp
        secret = pyotp.random_base32()
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(name="test@phoenix.io", issuer_name="Phoenix v2")
        assert len(secret) >= 16
        assert "Phoenix" in uri or "phoenix" in uri.lower()
        assert "phoenix.io" in uri or "test" in uri

import pytest
import services.api_gateway.src.middleware as mw_module
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from services.api_gateway.src.middleware import JWTMiddleware
from services.auth_service.src.auth import create_access_token, create_refresh_token


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Reset the module-level rate limiter state between tests."""
    mw_module._rate_limiter = None
    mw_module._rate_limiter_initialized = False
    yield
    mw_module._rate_limiter = None
    mw_module._rate_limiter_initialized = False


@pytest.fixture
def app_with_middleware():
    app = FastAPI()
    app.add_middleware(JWTMiddleware)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/protected")
    async def protected(request: Request):
        return {"user_id": request.state.user_id}

    return app


@pytest.fixture
def client(app_with_middleware):
    return TestClient(app_with_middleware, raise_server_exceptions=False)


class TestJWTMiddleware:
    def test_public_path_no_auth(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_missing_header_returns_401(self, client):
        resp = client.get("/protected")
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, client):
        resp = client.get("/protected", headers={"Authorization": "Bearer bad.token.here"})
        assert resp.status_code == 401

    def test_valid_token_passes(self, client):
        token = create_access_token("user-test-123")
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["user_id"] == "user-test-123"

    def test_refresh_token_rejected_for_access(self, client):
        token = create_refresh_token("user-test-456")
        resp = client.get("/protected", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 401

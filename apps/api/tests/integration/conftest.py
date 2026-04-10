import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from jose import jwt

from apps.api.src.config import auth_settings
from apps.api.src.main import app


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def auth_headers():
    token = jwt.encode(
        {"sub": "test-user-id", "type": "access", "admin": True, "role": "admin"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def non_admin_headers():
    token = jwt.encode(
        {"sub": "test-user-id", "type": "access", "admin": False, "role": "trader"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def invalid_headers():
    return {"Authorization": "Bearer invalid-token-value"}


@pytest.fixture
def sample_agent_payload():
    return {
        "name": "TestAgent",
        "type": "trading",
        "instance_id": "00000000-0000-0000-0000-000000000001",
        "config": {"strategy": "momentum"},
        "description": "A test agent",
        "data_source": "market",
        "skills": ["analysis"],
    }


@pytest.fixture
def sample_connector_payload():
    return {
        "name": "TestConnector",
        "type": "discord",
        "config": {"guild_id": "123456"},
        "credentials": {"token": "test-token"},
    }


@pytest.fixture
def sample_task_payload():
    return {
        "title": "Analyze AAPL momentum",
        "description": "Run momentum analysis on AAPL daily chart",
        "priority": "high",
        "status": "TODO",
    }

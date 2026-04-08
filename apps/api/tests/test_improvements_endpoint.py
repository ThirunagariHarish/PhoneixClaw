"""API integration tests for the Backtest CI endpoint.

Phase 0: Verifiable Alpha CI
POST /api/v2/agents/{agent_id}/improvements/{improvement_id}/run-backtest

Tests:
- 202 with valid BacktestCIResult shape
- 403 on wrong user_id  (IDOR)
- 404 on unknown agent
- 404 on missing improvement_id
- 409 on already-running backtest
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from jose import jwt

from apps.api.src.config import auth_settings
from apps.api.src.main import app
from shared.db.engine import get_session
from shared.db.models.agent import Agent

# ---------------------------------------------------------------------------
# Shared fake-session infrastructure (mirrors test_pm_endpoints.py pattern)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0


class FakeSession:
    def __init__(self, store: dict[type, list[Any]]) -> None:
        self.store = store
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any) -> _FakeResult:
        from sqlalchemy.sql import Select

        if isinstance(stmt, Select):
            entities: list[type] = []
            try:
                for d in stmt.column_descriptions or []:
                    e = d.get("entity")
                    if isinstance(e, type):
                        entities.append(e)
            except Exception:
                pass

            if not entities:
                from_objs = list(stmt.get_final_froms() or [])
                total = 0
                for fo in from_objs:
                    table_name = getattr(fo, "name", None) or getattr(
                        getattr(fo, "element", None), "name", None
                    )
                    for cls, rows in self.store.items():
                        if hasattr(cls, "__tablename__") and cls.__tablename__ == table_name:
                            total += len(rows)
                return _FakeResult([total])

            cls = entities[0]
            return _FakeResult(list(self.store.get(cls, [])))

        return _FakeResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.store.setdefault(type(obj), []).append(obj)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def refresh(self, obj: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_token(user_id: str, is_admin: bool = False) -> str:
    return jwt.encode(
        {
            "sub": user_id,
            "type": "access",
            "admin": is_admin,
            "role": "admin" if is_admin else "user",
        },
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )


def _make_agent(
    agent_id: uuid.UUID,
    user_id: uuid.UUID,
    pending_improvements: dict | None = None,
) -> Any:
    """Build a minimal Agent-like namespace compatible with agents.py route handlers."""
    now = datetime.now(timezone.utc)
    return types.SimpleNamespace(
        id=agent_id,
        user_id=user_id,
        name="Test Agent",
        type="trading",
        status="RUNNING",
        worker_status="RUNNING",
        config={},
        channel_name=None,
        analyst_name=None,
        model_type=None,
        model_accuracy=None,
        daily_pnl=0.0,
        total_pnl=0.0,
        total_trades=0,
        win_rate=0.0,
        current_mode="conservative",
        rules_version=1,
        last_signal_at=None,
        last_trade_at=None,
        last_activity_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        pending_improvements=pending_improvements or {"items": []},
        manifest={},
        phoenix_api_key="phx_test",
        source="manual",
    )


# ---------------------------------------------------------------------------
# Helper: patch BacktestCIService for endpoint tests
# ---------------------------------------------------------------------------

IMP_ID = "imp-test-001"
AGENT_UUID = uuid.uuid4()
OWNER_UUID = uuid.uuid4()
OTHER_UUID = uuid.uuid4()

_GOOD_IMPROVEMENT = {
    "id": IMP_ID,
    "type": "tighten_stop_loss",
    "description": "Tighten stop-loss",
    "backtest_passed": True,
    "backtest_status": "passed",
    "backtest_metrics": {
        "sharpe": 1.2,
        "win_rate": 0.60,
        "max_drawdown": -0.08,
        "profit_factor": 1.8,
        "trade_count": 30,
    },
    "backtest_run_at": datetime.now(timezone.utc).isoformat(),
    "backtest_thresholds_missed": [],
}

_RUNNING_IMPROVEMENT = {
    "id": IMP_ID,
    "type": "tighten_stop_loss",
    "backtest_status": "running",
}


# ---------------------------------------------------------------------------
# Test: 202 with valid shape
# ---------------------------------------------------------------------------


def test_run_backtest_returns_202_with_valid_shape():
    """Happy path: owner calls endpoint → 202 with BacktestCIResult shape."""
    agent = _make_agent(
        AGENT_UUID,
        OWNER_UUID,
        pending_improvements={
            "items": [{"id": IMP_ID, "type": "tighten_stop_loss", "description": "test"}]
        },
    )
    store: dict[type, list[Any]] = {Agent: [agent]}
    fake_session = FakeSession(store)

    async def _override():
        yield fake_session

    with patch(
        "apps.api.src.services.backtest_ci.BacktestCIService.run_ci_for_improvement",
        new_callable=AsyncMock,
        return_value=_GOOD_IMPROVEMENT,
    ):
        app.dependency_overrides[get_session] = _override
        try:
            client = TestClient(app, raise_server_exceptions=False)
            headers = {"Authorization": f"Bearer {_make_token(str(OWNER_UUID))}"}
            resp = client.post(
                f"/api/v2/agents/{AGENT_UUID}/improvements/{IMP_ID}/run-backtest",
                headers=headers,
            )
        finally:
            app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["improvement_id"] == IMP_ID
    assert isinstance(body["backtest_passed"], bool)
    assert body["backtest_status"] in ("passed", "failed", "borderline", "running", "pending")
    assert "backtest_metrics" in body
    assert "backtest_run_at" in body
    assert "thresholds_missed" in body


# ---------------------------------------------------------------------------
# Test: 403 IDOR — wrong user
# ---------------------------------------------------------------------------


def test_run_backtest_403_wrong_user():
    """Different user_id → 403 Forbidden."""
    agent = _make_agent(
        AGENT_UUID,
        OWNER_UUID,
        pending_improvements={
            "items": [{"id": IMP_ID, "type": "tighten_stop_loss"}]
        },
    )
    store: dict[type, list[Any]] = {Agent: [agent]}
    fake_session = FakeSession(store)

    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        headers = {"Authorization": f"Bearer {_make_token(str(OTHER_UUID))}"}
        resp = client.post(
            f"/api/v2/agents/{AGENT_UUID}/improvements/{IMP_ID}/run-backtest",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 403, resp.text


# ---------------------------------------------------------------------------
# Test: 403 bypassed for admin
# ---------------------------------------------------------------------------


def test_run_backtest_admin_can_access_any_agent():
    """Admin user can run CI on any agent regardless of ownership."""
    agent = _make_agent(
        AGENT_UUID,
        OWNER_UUID,
        pending_improvements={
            "items": [{"id": IMP_ID, "type": "tighten_stop_loss"}]
        },
    )
    store: dict[type, list[Any]] = {Agent: [agent]}
    fake_session = FakeSession(store)

    async def _override():
        yield fake_session

    with patch(
        "apps.api.src.services.backtest_ci.BacktestCIService.run_ci_for_improvement",
        new_callable=AsyncMock,
        return_value=_GOOD_IMPROVEMENT,
    ):
        app.dependency_overrides[get_session] = _override
        try:
            client = TestClient(app, raise_server_exceptions=False)
            # Admin token with a different user ID
            headers = {"Authorization": f"Bearer {_make_token(str(OTHER_UUID), is_admin=True)}"}
            resp = client.post(
                f"/api/v2/agents/{AGENT_UUID}/improvements/{IMP_ID}/run-backtest",
                headers=headers,
            )
        finally:
            app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 202, resp.text


# ---------------------------------------------------------------------------
# Test: 404 on unknown agent
# ---------------------------------------------------------------------------


def test_run_backtest_404_unknown_agent():
    """Agent not in DB → 404."""
    store: dict[type, list[Any]] = {Agent: []}  # empty store
    fake_session = FakeSession(store)

    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        headers = {"Authorization": f"Bearer {_make_token(str(OWNER_UUID))}"}
        resp = client.post(
            f"/api/v2/agents/{uuid.uuid4()}/improvements/{IMP_ID}/run-backtest",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Test: 404 on missing improvement_id
# ---------------------------------------------------------------------------


def test_run_backtest_404_missing_improvement():
    """Known agent but improvement_id does not exist → 404."""
    agent = _make_agent(
        AGENT_UUID,
        OWNER_UUID,
        pending_improvements={"items": []},  # no improvements
    )
    store: dict[type, list[Any]] = {Agent: [agent]}
    fake_session = FakeSession(store)

    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        headers = {"Authorization": f"Bearer {_make_token(str(OWNER_UUID))}"}
        resp = client.post(
            f"/api/v2/agents/{AGENT_UUID}/improvements/nonexistent-id/run-backtest",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 404, resp.text


# ---------------------------------------------------------------------------
# Test: 409 when backtest already running
# ---------------------------------------------------------------------------


def test_run_backtest_409_already_running():
    """Improvement with backtest_status='running' → 409 Conflict."""
    agent = _make_agent(
        AGENT_UUID,
        OWNER_UUID,
        pending_improvements={
            "items": [_RUNNING_IMPROVEMENT]
        },
    )
    store: dict[type, list[Any]] = {Agent: [agent]}
    fake_session = FakeSession(store)

    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override
    try:
        client = TestClient(app, raise_server_exceptions=False)
        headers = {"Authorization": f"Bearer {_make_token(str(OWNER_UUID))}"}
        resp = client.post(
            f"/api/v2/agents/{AGENT_UUID}/improvements/{IMP_ID}/run-backtest",
            headers=headers,
        )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert resp.status_code == 409, resp.text

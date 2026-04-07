"""
Phase 10 — Polymarket API route tests.

The PM ORM models use postgres-only types (UUID(as_uuid=True), JSONB) so we
cannot run them against an in-memory SQLite engine directly. Instead we
override the FastAPI `get_session` dependency with a tiny fake async session
that intercepts SQLAlchemy `select(...)` calls, returns canned in-memory rows
keyed by model class, and records `add()` so we can assert audit/attestation
side effects without a real database.

This still exercises:
  - URL routing + auth gate
  - Pydantic request validation
  - Pydantic response serialization
  - Filter wiring (parameters reach the handler)
  - Side-effect handlers (pause/resume/promote/demote/attest/kill switch)
"""

from __future__ import annotations

import types
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.sql import Select

from apps.api.src.config import auth_settings
from apps.api.src.main import app
from apps.api.src.routes import polymarket as pm_routes
from shared.db.engine import get_session
from shared.db.models.polymarket import (
    PMCalibrationSnapshot,
    PMJurisdictionAttestation,
    PMMarket,
    PMOrder,
    PMPosition,
    PMPromotionAudit,
    PMResolutionScore,
    PMStrategy,
)


# ---------------------------------------------------------------------------
# Fake DB session
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)

    def scalar_one_or_none(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0] if self._rows else 0


class FakeSession:
    """Minimal async session stand-in.

    `store` maps model class -> list of instances. `select(Model)` returns
    those instances; `func.count()` returns the length.
    """

    def __init__(self, store: dict[type, list[Any]]) -> None:
        self.store = store
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any) -> _FakeResult:
        # Detect count(*) selects: the statement's columns include a
        # function expression and the FROM clause carries the model.
        try:
            from sqlalchemy.sql.functions import count as _count_fn  # noqa: F401
        except Exception:  # pragma: no cover
            pass

        # `select(func.count()).select_from(Model)` -> Select with no
        # entity classes; fall back to total length of first store entry.
        if isinstance(stmt, Select):
            entities: list[type] = []
            try:
                desc = stmt.column_descriptions or []
                for d in desc:
                    e = d.get("entity")
                    if isinstance(e, type):
                        entities.append(e)
            except Exception:
                entities = []

            if not entities:
                # count(*) path; sum lengths of all known stores by inspecting
                # the FROM clause.
                from_objs = list(stmt.get_final_froms() or [])
                total = 0
                for fo in from_objs:
                    table_name = getattr(fo, "name", None) or getattr(
                        getattr(fo, "element", None), "name", None
                    )
                    for cls, rows in self.store.items():
                        if cls.__tablename__ == table_name:
                            total += len(rows)
                return _FakeResult([total])

            cls = entities[0]
            return _FakeResult(list(self.store.get(cls, [])))

        return _FakeResult([])

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        self.store.setdefault(type(obj), []).append(obj)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        return None

    async def close(self) -> None:
        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def store() -> dict[type, list[Any]]:
    return {}


@pytest.fixture
def fake_session(store: dict[type, list[Any]]) -> FakeSession:
    return FakeSession(store)


@pytest.fixture
def client(fake_session: FakeSession):
    async def _override():
        yield fake_session

    app.dependency_overrides[get_session] = _override
    # Reset PM kill switch between tests so state is isolated.
    pm_routes._pm_kill.active = False
    pm_routes._pm_kill.reason = ""
    pm_routes._pm_kill.activated_at = None
    # Note: no `with` context — avoid FastAPI lifespan hitting real Postgres.
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.pop(get_session, None)


@pytest.fixture
def user_uuid() -> uuid.UUID:
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def auth_headers(user_uuid: uuid.UUID) -> dict[str, str]:
    token = jwt.encode(
        {"sub": str(user_uuid), "type": "access", "admin": True, "role": "admin"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Helpers to build fake ORM rows without touching the DB
# ---------------------------------------------------------------------------


def _make_market(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "venue": "polymarket",
        "venue_market_id": "vm-1",
        "slug": "will-x-happen",
        "question": "Will X happen?",
        "category": "politics",
        "outcomes": [{"name": "YES"}, {"name": "NO"}],
        "total_volume": 12345.0,
        "liquidity_usd": 6789.0,
        "expiry": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "resolution_source": None,
        "oracle_type": "uma",
        "is_active": True,
        "last_scanned_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _make_strategy(**overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "strategy_id": uuid.uuid4(),
        "archetype": "sum_to_one_arb",
        "mode": "PAPER",
        "bankroll_usd": 5000.0,
        "max_strategy_notional_usd": 1000.0,
        "max_trade_notional_usd": 100.0,
        "kelly_cap": 0.25,
        "min_edge_bps": 50,
        "paused": False,
        "last_promotion_attempt_id": None,
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def _make_score(market_id: uuid.UUID, **overrides: Any) -> Any:
    defaults: dict[str, Any] = {
        "id": uuid.uuid4(),
        "pm_market_id": market_id,
        "oracle_type": "uma",
        "prior_disputes": 0,
        "llm_ambiguity_score": 0.1,
        "llm_rationale": "clean wording",
        "final_score": 0.92,
        "tradeable": True,
        "scored_at": datetime.now(timezone.utc),
        "model_version": "v1",
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------


def test_markets_requires_auth(client: TestClient):
    r = client.get("/api/polymarket/markets")
    assert r.status_code == 401


def test_strategies_requires_auth(client: TestClient):
    r = client.get("/api/polymarket/strategies")
    assert r.status_code == 401


def test_kill_switch_status_requires_auth(client: TestClient):
    r = client.get("/api/polymarket/kill-switch/status")
    assert r.status_code == 401


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------


def test_list_markets_empty(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/markets", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["markets"] == []
    assert body["total"] == 0
    assert "request_id" in body


def test_list_markets_returns_rows(
    client: TestClient, auth_headers, store: dict[type, list[Any]]
):
    store[PMMarket] = [_make_market(), _make_market(question="Will Y happen?")]
    r = client.get("/api/polymarket/markets?limit=10", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body["markets"]) == 2
    assert body["total"] == 2
    assert body["markets"][0]["venue"] == "polymarket"


def test_list_markets_validation_fail(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/markets?limit=9999", headers=auth_headers)
    assert r.status_code == 422


def test_get_market_not_found(client: TestClient, auth_headers):
    r = client.get(
        f"/api/polymarket/markets/{uuid.uuid4()}", headers=auth_headers
    )
    assert r.status_code == 404


def test_get_market_invalid_uuid(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/markets/not-a-uuid", headers=auth_headers)
    assert r.status_code == 400


def test_get_market_with_score(
    client: TestClient, auth_headers, store: dict[type, list[Any]]
):
    m = _make_market()
    store[PMMarket] = [m]
    store[PMResolutionScore] = [_make_score(m.id)]
    r = client.get(f"/api/polymarket/markets/{m.id}", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == str(m.id)
    assert body["resolution_score"]["tradeable"] is True
    assert body["resolution_score"]["final_score"] == 0.92


def test_force_scan(client: TestClient, auth_headers):
    r = client.post(
        "/api/polymarket/markets/scan", json={"venue": "polymarket"}, headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True
    assert "scan_id" in body


def test_resolution_risk_endpoint(
    client: TestClient, auth_headers, store: dict[type, list[Any]]
):
    mid = uuid.uuid4()
    store[PMResolutionScore] = [_make_score(mid)]
    r = client.get(
        f"/api/polymarket/markets/{mid}/resolution-risk", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["tradeable"] is True


def test_resolution_risk_missing(client: TestClient, auth_headers):
    r = client.get(
        f"/api/polymarket/markets/{uuid.uuid4()}/resolution-risk",
        headers=auth_headers,
    )
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------


def test_list_strategies(client: TestClient, auth_headers, store):
    store[PMStrategy] = [_make_strategy(), _make_strategy(archetype="cross_venue_arb")]
    r = client.get("/api/polymarket/strategies", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    assert {b["archetype"] for b in body} == {"sum_to_one_arb", "cross_venue_arb"}


def test_get_strategy_not_found(client: TestClient, auth_headers):
    r = client.get(
        f"/api/polymarket/strategies/{uuid.uuid4()}", headers=auth_headers
    )
    assert r.status_code == 404


def test_pause_resume(client: TestClient, auth_headers, store):
    s = _make_strategy(paused=False)
    store[PMStrategy] = [s]
    r = client.post(
        f"/api/polymarket/strategies/{s.id}/pause", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["paused"] is True
    assert s.paused is True

    r2 = client.post(
        f"/api/polymarket/strategies/{s.id}/resume", headers=auth_headers
    )
    assert r2.status_code == 200
    assert r2.json()["paused"] is False
    assert s.paused is False


def test_promote_validation_fail(client: TestClient, auth_headers, store):
    s = _make_strategy()
    store[PMStrategy] = [s]
    r = client.post(
        f"/api/polymarket/strategies/{s.id}/promote",
        json={"typed_confirmation": "PROMOTE", "max_notional_first_week": -1, "ack_resolution_risk": True},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_promote_requires_ack(client: TestClient, auth_headers, store):
    s = _make_strategy()
    store[PMStrategy] = [s]
    r = client.post(
        f"/api/polymarket/strategies/{s.id}/promote",
        json={"typed_confirmation": "PROMOTE", "max_notional_first_week": 500, "ack_resolution_risk": False},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_promote_typed_confirmation_must_match_archetype(
    client: TestClient, auth_headers, store
):
    # M1: server-side check — typed_confirmation must equal strategy archetype.
    s = _make_strategy(archetype="sum_to_one_arb")
    store[PMStrategy] = [s]
    r = client.post(
        f"/api/polymarket/strategies/{s.id}/promote",
        json={
            "typed_confirmation": "PROMOTE",  # wrong
            "max_notional_first_week": 500,
            "ack_resolution_risk": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 400
    assert "archetype" in r.json()["detail"]


def test_promote_runs_real_engine_and_fails_on_empty_history(
    client: TestClient, auth_headers, store
):
    # B1: the route now wires the real PromotionGateEngine. A strategy with no
    # trades / no calibration fails the soak/trade/calibration checks and
    # stays in PAPER; an audit row is written with structured failure reasons.
    s = _make_strategy(archetype="sum_to_one_arb")
    store[PMStrategy] = [s]
    r = client.post(
        f"/api/polymarket/strategies/{s.id}/promote",
        json={
            "typed_confirmation": "sum_to_one_arb",  # matches archetype
            "max_notional_first_week": 500,
            "ack_resolution_risk": True,
        },
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert "audit_id" in body
    assert body["failure_reasons"], "expected structured failure reasons from real engine"
    ge = body["gate_evaluations"]
    # Real engine output shape — not the old stub's TODO payload.
    assert "checks" in ge
    assert "config_snapshot" in ge
    assert "metrics_snapshot" in ge
    # Strategy must remain in PAPER on a failed gate.
    assert s.mode == "PAPER"
    assert any(isinstance(a, PMPromotionAudit) for a in store.get(PMPromotionAudit, []))


def test_demote(client: TestClient, auth_headers, store):
    s = _make_strategy(mode="LIVE")
    store[PMStrategy] = [s]
    r = client.post(
        f"/api/polymarket/strategies/{s.id}/demote",
        json={"reason": "manual safety"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["success"] is True
    assert s.mode == "PAPER"


def test_promotion_audit_list(client: TestClient, auth_headers, store):
    sid = uuid.uuid4()
    audit = types.SimpleNamespace(
        id=uuid.uuid4(),
        pm_strategy_id=sid,
        actor_user_id=None,
        action="attempt",
        outcome="failed",
        gate_evaluations={"soak_days": {"passed": False}},
        previous_mode="PAPER",
        new_mode="PAPER",
        notes=None,
        attached_backtest_id=None,
        jurisdiction_attestation_id=None,
        created_at=datetime.now(timezone.utc),
    )
    store[PMPromotionAudit] = [audit]
    r = client.get(
        f"/api/polymarket/strategies/{sid}/promotion_audit", headers=auth_headers
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["action"] == "attempt"


def test_calibration_unavailable(client: TestClient, auth_headers):
    r = client.get(
        f"/api/polymarket/strategies/{uuid.uuid4()}/calibration", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.json()["available"] is False


def test_calibration_available(client: TestClient, auth_headers, store):
    sid = uuid.uuid4()
    snap = types.SimpleNamespace(
        id=uuid.uuid4(),
        pm_strategy_id=sid,
        category=None,
        window_days=30,
        n_trades=75,
        n_resolved=50,
        brier=0.18,
        log_loss=0.42,
        reliability_bins=[],
        sharpe=1.2,
        max_drawdown_pct=3.4,
        computed_at=datetime.now(timezone.utc),
    )
    store[PMCalibrationSnapshot] = [snap]
    r = client.get(
        f"/api/polymarket/strategies/{sid}/calibration?window_days=30",
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["n_trades"] == 75
    assert body["brier"] == 0.18


# ---------------------------------------------------------------------------
# Orders / positions
# ---------------------------------------------------------------------------


def test_list_orders_empty(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/orders", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == []


def test_list_orders(client: TestClient, auth_headers, store):
    o = types.SimpleNamespace(
        id=uuid.uuid4(),
        pm_strategy_id=uuid.uuid4(),
        pm_market_id=uuid.uuid4(),
        outcome_token_id="tok-1",
        side="BUY",
        qty_shares=100.0,
        limit_price=0.42,
        mode="PAPER",
        status="FILLED",
        venue_order_id=None,
        fees_paid_usd=0.05,
        slippage_bps=1.0,
        f9_score=0.9,
        jurisdiction_attestation_id=None,
        arb_group_id=None,
        submitted_at=datetime.now(timezone.utc),
        filled_at=datetime.now(timezone.utc),
        cancelled_at=None,
    )
    store[PMOrder] = [o]
    r = client.get("/api/polymarket/orders", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["status"] == "FILLED"


def test_list_positions_validation_fail(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/positions?mode=BOGUS", headers=auth_headers)
    assert r.status_code == 422


def test_list_positions(client: TestClient, auth_headers, store):
    p = types.SimpleNamespace(
        id=uuid.uuid4(),
        pm_strategy_id=uuid.uuid4(),
        pm_market_id=uuid.uuid4(),
        outcome_token_id="tok-1",
        qty_shares=100.0,
        avg_entry_price=0.42,
        mode="PAPER",
        unrealized_pnl_usd=5.0,
        realized_pnl_usd=0.0,
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
    )
    store[PMPosition] = [p]
    r = client.get("/api/polymarket/positions?mode=PAPER", headers=auth_headers)
    assert r.status_code == 200
    assert len(r.json()) == 1


# ---------------------------------------------------------------------------
# Jurisdiction attestation
# ---------------------------------------------------------------------------


def test_attest_requires_ack(client: TestClient, auth_headers):
    r = client.post(
        "/api/polymarket/jurisdiction/attest",
        json={"ack_geoblock": False, "attestation_text_hash": "abcdefgh"},
        headers=auth_headers,
    )
    assert r.status_code == 400


def test_attest_validation_fail(client: TestClient, auth_headers):
    r = client.post(
        "/api/polymarket/jurisdiction/attest",
        json={"ack_geoblock": True, "attestation_text_hash": "x"},
        headers=auth_headers,
    )
    assert r.status_code == 422


def test_attest_success_then_current(
    client: TestClient, auth_headers, store
):
    r = client.post(
        "/api/polymarket/jurisdiction/attest",
        json={"ack_geoblock": True, "attestation_text_hash": "abcdefgh1234"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert "id" in body
    assert "valid_until" in body
    # `add()` recorded the row in the store under PMJurisdictionAttestation
    assert PMJurisdictionAttestation in store
    assert len(store[PMJurisdictionAttestation]) == 1

    r2 = client.get("/api/polymarket/jurisdiction/current", headers=auth_headers)
    assert r2.status_code == 200
    assert r2.json()["valid"] is True


def test_current_attestation_none(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/jurisdiction/current", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["valid"] is False


def test_current_attestation_expired(client: TestClient, auth_headers, store, user_uuid):
    att = types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_uuid,
        attestation_text_hash="x" * 64,
        acknowledged_geoblock=True,
        ip_at_attestation=None,
        user_agent=None,
        valid_until=datetime.now(timezone.utc) - timedelta(days=1),
        created_at=datetime.now(timezone.utc) - timedelta(days=40),
    )
    store[PMJurisdictionAttestation] = [att]
    r = client.get("/api/polymarket/jurisdiction/current", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["valid"] is False


# ---------------------------------------------------------------------------
# Kill switch
# ---------------------------------------------------------------------------


def test_kill_switch_lifecycle(client: TestClient, auth_headers):
    r = client.get("/api/polymarket/kill-switch/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["active"] is False

    r = client.post(
        "/api/polymarket/kill-switch/activate",
        json={"reason": "incident-1"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["active"] is True

    r = client.get("/api/polymarket/kill-switch/status", headers=auth_headers)
    assert r.json()["active"] is True
    assert r.json()["reason"] == "incident-1"

    # Wrong typed confirmation -> 400
    r = client.post(
        "/api/polymarket/kill-switch/deactivate",
        json={"typed_confirmation": "no"},
        headers=auth_headers,
    )
    assert r.status_code == 400

    r = client.post(
        "/api/polymarket/kill-switch/deactivate",
        json={"typed_confirmation": "REARM"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["active"] is False


def test_kill_switch_deactivate_requires_admin(client: TestClient, user_uuid):
    # M8: non-admin caller must get 403 on deactivate. Activate (PM-scoped)
    # stays open to any authenticated user because "halt faster" is safe.
    viewer_token = jwt.encode(
        {"sub": str(user_uuid), "type": "access", "admin": False, "role": "viewer"},
        auth_settings.jwt_secret_key,
        algorithm=auth_settings.jwt_algorithm,
    )
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    act = client.post(
        "/api/polymarket/kill-switch/activate",
        json={"reason": "test"},
        headers=viewer_headers,
    )
    assert act.status_code == 200

    deact = client.post(
        "/api/polymarket/kill-switch/deactivate",
        json={"typed_confirmation": "REARM"},
        headers=viewer_headers,
    )
    assert deact.status_code == 403


def test_kill_switch_activate_validation_fail(client: TestClient, auth_headers):
    r = client.post(
        "/api/polymarket/kill-switch/activate",
        json={"reason": ""},
        headers=auth_headers,
    )
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# Briefing
# ---------------------------------------------------------------------------


def test_briefing_section(client: TestClient, auth_headers, store):
    p = types.SimpleNamespace(
        id=uuid.uuid4(),
        pm_strategy_id=uuid.uuid4(),
        pm_market_id=uuid.uuid4(),
        outcome_token_id="tok-1",
        qty_shares=10.0,
        avg_entry_price=0.5,
        mode="PAPER",
        unrealized_pnl_usd=3.0,
        realized_pnl_usd=1.0,
        opened_at=datetime.now(timezone.utc),
        closed_at=None,
    )
    store[PMPosition] = [p]
    r = client.get("/api/polymarket/briefing/section", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["paper_pnl"] == 4.0
    assert body["live_pnl"] == 0.0
    assert "kill_switch" in body

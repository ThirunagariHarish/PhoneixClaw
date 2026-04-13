"""Unit tests for the Phoenix Inference Service (v2 — agent-scoped models)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from services.inference_service.src import main as inference_main
from services.inference_service.src.main import (
    AgentModelBundle,
    PredictRequest,
    PredictResponse,
    _prepare_feature_vector,
    _run_prediction,
    app,
)

AGENT_A = str(uuid.uuid4())
AGENT_B = str(uuid.uuid4())
BUNDLE_ID = str(uuid.uuid4())


def _make_bundle(
    agent_id: str = AGENT_A,
    bundle_id: str = BUNDLE_ID,
    version: int = 1,
    primary_model: str = "lightgbm",
    model: object | None = None,
    feature_columns: list[str] | None = None,
    preprocessor: dict | None = None,
    patterns: dict | None = None,
) -> AgentModelBundle:
    if model is None:
        model = MagicMock()
        model.predict_proba = MagicMock(return_value=np.array([[0.2, 0.8]]))
        model.predict = MagicMock(return_value=np.array([1]))
    return AgentModelBundle(
        agent_id=agent_id,
        bundle_id=bundle_id,
        version=version,
        minio_path=f"models/{agent_id}/v{version}/bundle.tar.gz",
        models={primary_model: model},
        preprocessor=preprocessor or {},
        meta={},
        feature_columns=["rsi_14", "macd", "volume_ratio"] if feature_columns is None else feature_columns,
        primary_model=primary_model,
        patterns=patterns or {},
    )


@pytest.fixture(autouse=True)
def _reset_globals():
    """Reset module-level state between tests."""
    original = inference_main._agent_models.copy()
    yield
    inference_main._agent_models.clear()
    inference_main._agent_models.update(original)


@pytest.fixture()
def mock_model():
    model = MagicMock()
    model.predict_proba = MagicMock(return_value=np.array([[0.2, 0.8]]))
    model.predict = MagicMock(return_value=np.array([1]))
    return model


@pytest.fixture()
def mock_model_no_proba():
    model = MagicMock(spec=["predict"])
    model.predict.return_value = np.array([0])
    return model


@pytest.fixture()
def loaded_state(mock_model):
    bundle = _make_bundle(agent_id=AGENT_A, model=mock_model)
    inference_main._agent_models.clear()
    inference_main._agent_models[AGENT_A] = bundle
    return bundle


# ── AgentModelBundle dataclass ──────────────────────────────────────────────


class TestAgentModelBundle:
    def test_defaults(self):
        b = AgentModelBundle(agent_id="a", bundle_id="b", version=1, minio_path="p")
        assert b.models == {}
        assert b.preprocessor == {}
        assert b.feature_columns == []
        assert isinstance(b.loaded_at, datetime)
        assert isinstance(b.last_used, datetime)

    def test_explicit_values(self):
        b = _make_bundle(version=3)
        assert b.version == 3
        assert b.primary_model == "lightgbm"


# ── Feature vector preparation ──────────────────────────────────────────────


class TestPrepareFeatureVector:
    def test_merges_feature_store_and_signal_features(self):
        bundle = _make_bundle(feature_columns=["rsi_14", "macd", "volume_ratio"])
        df = _prepare_feature_vector(bundle, {"rsi_14": 45.0, "macd": 0.5}, {"volume_ratio": 1.2})
        assert list(df.columns) == ["rsi_14", "macd", "volume_ratio"]
        assert df.shape == (1, 3)
        assert df["rsi_14"].iloc[0] == pytest.approx(45.0)
        assert df["volume_ratio"].iloc[0] == pytest.approx(1.2)

    def test_missing_columns_filled_with_zero(self):
        bundle = _make_bundle(feature_columns=["rsi_14", "missing_col"])
        df = _prepare_feature_vector(bundle, {"rsi_14": 50.0}, {})
        assert df.shape == (1, 2)
        assert df["missing_col"].iloc[0] == 0.0

    def test_imputer_applied(self):
        mock_imputer = MagicMock()
        mock_imputer.transform.return_value = np.array([[1.0, 2.0]])
        bundle = _make_bundle(
            feature_columns=["a", "b"],
            preprocessor={"imputer": mock_imputer},
        )
        df = _prepare_feature_vector(bundle, {"a": np.nan}, {"b": np.nan})
        mock_imputer.transform.assert_called_once()
        assert df["a"].iloc[0] == pytest.approx(1.0)
        assert df["b"].iloc[0] == pytest.approx(2.0)

    def test_scaler_applied(self):
        mock_scaler = MagicMock()
        mock_scaler.transform.return_value = np.array([[-1.0, 1.0]])
        bundle = _make_bundle(
            feature_columns=["a", "b"],
            preprocessor={"scaler": mock_scaler},
        )
        df = _prepare_feature_vector(bundle, {"a": 10.0, "b": 20.0}, {})
        mock_scaler.transform.assert_called_once()
        assert df["a"].iloc[0] == pytest.approx(-1.0)

    def test_no_feature_columns_uses_numeric_keys(self):
        bundle = _make_bundle(feature_columns=[])
        df = _prepare_feature_vector(bundle, {"price": 100.0, "text_field": "hello"}, {"vol": 5.0})
        assert "price" in df.columns
        assert "vol" in df.columns
        assert "text_field" not in df.columns

    def test_signal_features_override_feature_store(self):
        bundle = _make_bundle(feature_columns=["rsi_14"])
        df = _prepare_feature_vector(bundle, {"rsi_14": 30.0}, {"rsi_14": 70.0})
        assert df["rsi_14"].iloc[0] == pytest.approx(70.0)


# ── Prediction logic ────────────────────────────────────────────────────────


class TestRunPrediction:
    def test_trade_prediction(self, mock_model):
        mock_model.predict_proba.return_value = np.array([[0.15, 0.85]])
        bundle = _make_bundle(model=mock_model)
        df = pd.DataFrame({"rsi_14": [45.0], "macd": [0.5], "volume_ratio": [1.2]})
        pred, conf, reasoning = _run_prediction(bundle, df)
        assert pred == "TRADE"
        assert conf == pytest.approx(0.85, abs=0.01)
        assert "lightgbm" in reasoning

    def test_skip_prediction(self, mock_model):
        mock_model.predict_proba.return_value = np.array([[0.9, 0.1]])
        bundle = _make_bundle(model=mock_model)
        df = pd.DataFrame({"rsi_14": [45.0]})
        pred, conf, reasoning = _run_prediction(bundle, df)
        assert pred == "SKIP"
        assert conf == pytest.approx(0.9, abs=0.01)

    def test_model_without_predict_proba(self, mock_model_no_proba):
        bundle = _make_bundle(model=mock_model_no_proba)
        df = pd.DataFrame({"rsi_14": [45.0]})
        pred, conf, reasoning = _run_prediction(bundle, df)
        assert pred == "SKIP"
        assert conf == 0.5

    def test_no_model_raises(self):
        bundle = _make_bundle()
        bundle.models = {}
        df = pd.DataFrame({"rsi_14": [45.0]})
        with pytest.raises(RuntimeError, match="not loaded"):
            _run_prediction(bundle, df)

    def test_raw_bytes_model_raises(self):
        bundle = _make_bundle()
        bundle.models["lightgbm"] = b"raw-pytorch-bytes"
        df = pd.DataFrame({"rsi_14": [45.0]})
        with pytest.raises(RuntimeError, match="raw bytes"):
            _run_prediction(bundle, df)

    def test_pattern_notes_in_reasoning(self, mock_model):
        mock_model.predict_proba.return_value = np.array([[0.3, 0.7]])
        bundle = _make_bundle(
            model=mock_model,
            patterns={"momentum_breakout": {"active": True}, "mean_reversion": {"active": False}},
        )
        df = pd.DataFrame({"rsi_14": [45.0]})
        _, _, reasoning = _run_prediction(bundle, df)
        assert "Active patterns" in reasoning
        assert "momentum_breakout" in reasoning

    def test_no_primary_model_raises(self):
        bundle = _make_bundle()
        bundle.primary_model = None
        df = pd.DataFrame({"rsi_14": [45.0]})
        with pytest.raises(RuntimeError, match="no primary model"):
            _run_prediction(bundle, df)


# ── load_models_from_directory ──────────────────────────────────────────────


class TestLoadModelsFromDirectory:
    def test_loads_primary_from_best_model_json(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "best_model.json").write_text(json.dumps({"model_name": "xgboost"}))
        (models_dir / "meta.json").write_text(json.dumps({"feature_columns": ["a", "b"]}))
        (models_dir / "imputer.pkl").touch()
        (models_dir / "scaler.pkl").touch()

        mock_model = MagicMock()
        p1 = patch("services.inference_service.src.main._load_model_file", return_value=(mock_model, "xgboost (pkl)"))
        p2 = patch("services.inference_service.src.main._load_pkl", return_value=MagicMock())
        with p1, p2:
            bundle = inference_main.load_models_from_directory(
                models_dir, agent_id="agent-1", bundle_id="b-1", version=2, minio_path="m/p",
            )

        assert bundle is not None
        assert bundle.primary_model == "xgboost"
        assert bundle.feature_columns == ["a", "b"]
        assert bundle.bundle_id == "b-1"
        assert bundle.version == 2

    def test_fallback_chain_when_primary_not_found(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "meta.json").write_text(json.dumps({"feature_columns": []}))

        call_models = []

        def fake_load(d, name):
            call_models.append(name)
            if name == "lightgbm":
                return MagicMock(), "lightgbm (pkl)"
            return None, ""

        with patch("services.inference_service.src.main._load_model_file", side_effect=fake_load):
            bundle = inference_main.load_models_from_directory(
                models_dir, agent_id="agent-2", bundle_id="b-2", version=1, minio_path="m/p",
            )

        assert bundle is not None
        assert bundle.primary_model == "lightgbm"
        assert "lightgbm" in call_models

    def test_returns_none_when_no_model_found(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()

        with patch("services.inference_service.src.main._load_model_file", return_value=(None, "")):
            bundle = inference_main.load_models_from_directory(
                models_dir, agent_id="agent-3", bundle_id="b-3", version=1, minio_path="m/p",
            )

        assert bundle is None

    def test_loads_patterns(self, tmp_path):
        models_dir = tmp_path / "models"
        models_dir.mkdir()
        (models_dir / "best_model.json").write_text(json.dumps({"model_name": "lgb"}))
        (models_dir / "patterns.json").write_text(json.dumps({"gap_fill": {"active": True}}))

        with patch("services.inference_service.src.main._load_model_file", return_value=(MagicMock(), "lgb (pkl)")):
            bundle = inference_main.load_models_from_directory(
                models_dir, agent_id="a", bundle_id="b", version=1, minio_path="p",
            )

        assert bundle is not None
        assert bundle.patterns == {"gap_fill": {"active": True}}


# ── LRU eviction ────────────────────────────────────────────────────────────


class TestLRUEviction:
    def test_evicts_oldest_when_over_limit(self):
        inference_main._agent_models.clear()
        original_max = inference_main.MAX_LOADED_MODELS
        inference_main.MAX_LOADED_MODELS = 2
        try:
            inference_main._agent_models["a1"] = _make_bundle(agent_id="a1")
            inference_main._agent_models["a2"] = _make_bundle(agent_id="a2")
            inference_main._agent_models["a3"] = _make_bundle(agent_id="a3")
            inference_main._evict_lru_if_needed()
            assert "a1" not in inference_main._agent_models
            assert "a2" in inference_main._agent_models
            assert "a3" in inference_main._agent_models
            assert len(inference_main._agent_models) == 2
        finally:
            inference_main.MAX_LOADED_MODELS = original_max

    def test_no_eviction_under_limit(self):
        inference_main._agent_models.clear()
        inference_main._agent_models["a1"] = _make_bundle(agent_id="a1")
        inference_main._evict_lru_if_needed()
        assert "a1" in inference_main._agent_models


# ── Predict endpoint ────────────────────────────────────────────────────────


class TestPredictEndpoint:
    @patch("services.inference_service.src.main._log_prediction", new_callable=AsyncMock)
    @patch("services.inference_service.src.main.FeatureStoreClient")
    def test_predict_success(self, mock_fs_cls, mock_log_pred, loaded_state, mock_model):
        mock_model.predict_proba.return_value = np.array([[0.2, 0.8]])

        mock_fs_instance = AsyncMock()
        mock_fs_instance.read_feature_view.return_value = {"rsi_14": 45.0, "macd": 0.5, "volume_ratio": 1.2}
        mock_fs_cls.return_value = mock_fs_instance

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/predict", json={
                "ticker": "PLTR",
                "agent_id": AGENT_A,
                "signal_features": {"direction": "BUY"},
            })

        assert response.status_code == 200
        data = response.json()
        assert data["prediction"] in ("TRADE", "SKIP")
        assert "confidence" in data
        assert data["model"] == "lightgbm"

    def test_predict_no_model_returns_skip(self):
        inference_main._agent_models.clear()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/predict", json={
                "ticker": "AAPL",
                "agent_id": str(uuid.uuid4()),
                "signal_features": {},
            })

        assert response.status_code == 200
        data = response.json()
        assert data["prediction"] == "SKIP"
        assert data["confidence"] == 0.0
        assert data["reasoning"] == "no_model_for_agent"
        assert data["model"] == "none"

    def test_predict_invalid_agent_id_returns_400(self, loaded_state):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/predict", json={
                "ticker": "AAPL",
                "agent_id": "not-a-uuid",
                "signal_features": {},
            })

        assert response.status_code == 400

    @patch("services.inference_service.src.main._log_prediction", new_callable=AsyncMock)
    @patch("services.inference_service.src.main.FeatureStoreClient")
    def test_predict_uses_correct_agent_model(self, mock_fs_cls, mock_log_pred):
        model_a = MagicMock()
        model_a.predict_proba = MagicMock(return_value=np.array([[0.1, 0.9]]))
        model_b = MagicMock()
        model_b.predict_proba = MagicMock(return_value=np.array([[0.8, 0.2]]))

        inference_main._agent_models.clear()
        inference_main._agent_models[AGENT_A] = _make_bundle(agent_id=AGENT_A, model=model_a)
        inference_main._agent_models[AGENT_B] = _make_bundle(agent_id=AGENT_B, model=model_b)

        mock_fs_instance = AsyncMock()
        mock_fs_instance.read_feature_view.return_value = {}
        mock_fs_cls.return_value = mock_fs_instance

        with TestClient(app, raise_server_exceptions=False) as client:
            resp_a = client.post("/predict", json={
                "ticker": "AAPL",
                "agent_id": AGENT_A,
                "signal_features": {},
            })
            resp_b = client.post("/predict", json={
                "ticker": "AAPL",
                "agent_id": AGENT_B,
                "signal_features": {},
            })

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200
        assert resp_a.json()["prediction"] == "TRADE"
        assert resp_b.json()["prediction"] == "SKIP"


# ── Models endpoint ─────────────────────────────────────────────────────────


class TestModelsEndpoint:
    def test_list_models_empty(self):
        inference_main._agent_models.clear()
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/models")
        assert response.status_code == 200
        data = response.json()
        assert data["loaded_agents"] == 0
        assert data["agents"] == []

    def test_list_models_with_agents(self, loaded_state):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/models")
        assert response.status_code == 200
        data = response.json()
        assert data["loaded_agents"] == 1
        assert len(data["agents"]) == 1
        agent_entry = data["agents"][0]
        assert agent_entry["agent_id"] == AGENT_A
        assert agent_entry["primary_model"] == "lightgbm"
        assert "loaded_at" in agent_entry
        assert "last_used" in agent_entry


# ── Reload endpoint ─────────────────────────────────────────────────────────


class TestReloadEndpoint:
    @patch("services.inference_service.src.main._load_all_approved_bundles", new_callable=AsyncMock)
    def test_reload_all_success(self, mock_load):
        mock_load.return_value = 2

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/models/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reloaded"
        assert data["agents_loaded"] == 2

    @patch("services.inference_service.src.main._load_all_approved_bundles", new_callable=AsyncMock)
    def test_reload_all_failure(self, mock_load):
        mock_load.return_value = 0

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/models/reload")

        assert response.status_code == 404

    @patch("services.inference_service.src.main._load_agent_bundle", new_callable=AsyncMock)
    def test_reload_single_agent_success(self, mock_load):
        agent_id = str(uuid.uuid4())
        mock_load.return_value = True
        inference_main._agent_models[agent_id] = _make_bundle(agent_id=agent_id)

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/models/reload?agent_id={agent_id}")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "reloaded"
        assert data["agent_id"] == agent_id

    @patch("services.inference_service.src.main._load_agent_bundle", new_callable=AsyncMock)
    def test_reload_single_agent_not_found(self, mock_load):
        mock_load.return_value = False

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post(f"/models/reload?agent_id={uuid.uuid4()}")

        assert response.status_code == 404

    def test_reload_invalid_agent_id(self):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.post("/models/reload?agent_id=not-a-uuid")

        assert response.status_code == 400


# ── Health endpoint ─────────────────────────────────────────────────────────


class TestHealthEndpoint:
    def test_health_with_models(self, loaded_state):
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["model_loaded"] is True
        assert data["loaded_agents"] == 1
        assert AGENT_A in data["agent_ids"]

    def test_health_without_models(self):
        inference_main._agent_models.clear()

        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "no_model"
        assert data["model_loaded"] is False
        assert data["loaded_agents"] == 0


# ── Pydantic models ────────────────────────────────────────────────────────


class TestPredictRequest:
    def test_valid_request(self):
        req = PredictRequest(ticker="PLTR", agent_id=str(uuid.uuid4()), signal_features={"direction": "BUY"})
        assert req.ticker == "PLTR"

    def test_defaults(self):
        req = PredictRequest(ticker="AAPL", agent_id=str(uuid.uuid4()))
        assert req.signal_features == {}


class TestPredictResponse:
    def test_valid_response(self):
        resp = PredictResponse(
            prediction="TRADE",
            confidence=0.82,
            reasoning="test reasoning",
            model="lightgbm",
            feature_count=200,
        )
        assert resp.prediction == "TRADE"
        assert resp.confidence == 0.82


# ── MinIO client helper ────────────────────────────────────────────────────


class TestMinioClient:
    def test_minio_client_strips_http(self):
        with patch.dict("os.environ", {
            "MINIO_ENDPOINT": "http://localhost:9000",
            "MINIO_ACCESS_KEY": "key",
            "MINIO_SECRET_KEY": "secret",
        }):
            inference_main.MINIO_ENDPOINT = "http://localhost:9000"
            inference_main.MINIO_ACCESS_KEY = "key"
            inference_main.MINIO_SECRET_KEY = "secret"
            client = inference_main._minio_client()
            assert client is not None

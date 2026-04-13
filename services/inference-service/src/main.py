"""Phoenix Inference Service — serves ML model predictions.

Loads trained model bundles from MinIO (as tarballs), runs inference against
Feature Store features, and logs every prediction to the predictions table
for accuracy monitoring and drift detection.

Each agent gets its own model bundle.  Models are selected per-agent on every
``POST /predict`` call so multiple live agents can coexist.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import redis.asyncio as aioredis
from fastapi import FastAPI, HTTPException, Query
from minio import Minio
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.feature_store.client import FeatureStoreClient

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://phoenixtrader:localdev@localhost:5432/phoenixtrader",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
MINIO_ENDPOINT = os.environ.get("MINIO_ENDPOINT", "http://minio:9000")
MINIO_ACCESS_KEY = os.environ.get("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.environ.get("MINIO_SECRET_KEY", "minioadmin")
MODEL_BUCKET = os.environ.get("MODEL_BUCKET", "phoenix-models")
MAX_LOADED_MODELS = int(os.environ.get("MAX_LOADED_MODELS", "25"))

_engine = create_async_engine(DATABASE_URL, pool_size=5, max_overflow=5)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)
_redis: aioredis.Redis | None = None

MODEL_FALLBACK_CHAIN = ["lightgbm", "xgboost", "random_forest"]


@dataclass
class AgentModelBundle:
    agent_id: str
    bundle_id: str
    version: int
    minio_path: str
    models: dict[str, Any] = field(default_factory=dict)
    preprocessor: dict[str, Any] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)
    feature_columns: list[str] = field(default_factory=list)
    primary_model: str | None = None
    patterns: dict = field(default_factory=dict)
    loaded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_used: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_agent_models: OrderedDict[str, AgentModelBundle] = OrderedDict()


class PredictRequest(BaseModel):
    ticker: str
    agent_id: str
    signal_features: dict[str, Any] = {}


class PredictResponse(BaseModel):
    prediction: str
    confidence: float
    reasoning: str
    model: str
    feature_count: int


def _minio_client() -> Minio:
    endpoint = MINIO_ENDPOINT.replace("http://", "").replace("https://", "")
    secure = MINIO_ENDPOINT.startswith("https://")
    return Minio(endpoint, access_key=MINIO_ACCESS_KEY, secret_key=MINIO_SECRET_KEY, secure=secure)


def _load_pkl(path: Path) -> Any:
    return joblib.load(path)


def _load_catboost_model(path: Path) -> Any:
    from catboost import CatBoostClassifier
    model = CatBoostClassifier()
    model.load_model(str(path))
    return model


def _load_model_file(models_dir: Path, model_name: str) -> tuple[Any, str]:
    """Try to load a model by name from extracted bundle directory."""
    pkl_path = models_dir / f"{model_name}_model.pkl"
    if pkl_path.exists():
        return _load_pkl(pkl_path), f"{model_name} (pkl)"

    cbm_path = models_dir / f"{model_name}_model.cbm"
    if cbm_path.exists():
        try:
            return _load_catboost_model(cbm_path), f"{model_name} (cbm)"
        except ImportError:
            log.warning("CatBoost not installed, skipping %s", cbm_path)

    pt_path = models_dir / f"{model_name}_model.pt"
    if pt_path.exists():
        log.warning("PyTorch model found but loading deferred — returning raw bytes for %s", model_name)
        return pt_path.read_bytes(), f"{model_name} (pt-raw)"

    return None, ""


def _download_and_extract_bundle(minio_path: str) -> Path:
    """Download a tarball from MinIO and extract it to a temp directory.

    Returns the path to the directory containing the extracted model files.
    """
    client = _minio_client()
    dest_dir = Path(tempfile.mkdtemp(prefix="phoenix_model_"))
    models_dir = dest_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    import io
    import tarfile

    response = client.get_object(MODEL_BUCKET, minio_path)
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()

    tar_buffer = io.BytesIO(data)
    with tarfile.open(fileobj=tar_buffer, mode="r:gz") as tar:
        tar.extractall(path=models_dir, filter="data")

    log.info("Extracted bundle %s to %s", minio_path, models_dir)
    return models_dir


def load_models_from_directory(
    models_dir: Path,
    agent_id: str,
    bundle_id: str,
    version: int,
    minio_path: str,
) -> AgentModelBundle | None:
    """Load all model artifacts from an extracted bundle directory.

    Returns an AgentModelBundle on success, None if no usable model found.
    """
    best_model_path = models_dir / "best_model.json"
    primary_model_name: str | None = None
    if best_model_path.exists():
        best_info = json.loads(best_model_path.read_text())
        primary_model_name = best_info.get("model_name") or best_info.get("best_model")
        log.info("best_model.json designates primary: %s", primary_model_name)

    meta_path = models_dir / "meta.json"
    meta: dict = {}
    feature_columns: list[str] = []
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        feature_columns = meta.get("feature_columns", [])
        log.info("Loaded meta.json with %d feature columns", len(feature_columns))

    loaded_models: dict[str, Any] = {}
    preprocessor: dict[str, Any] = {}

    imputer_path = models_dir / "imputer.pkl"
    if imputer_path.exists():
        preprocessor["imputer"] = _load_pkl(imputer_path)
        log.info("Loaded imputer.pkl")

    scaler_path = models_dir / "scaler.pkl"
    if scaler_path.exists():
        preprocessor["scaler"] = _load_pkl(scaler_path)
        log.info("Loaded scaler.pkl")

    resolved_primary: str | None = None

    if primary_model_name:
        model_obj, label = _load_model_file(models_dir, primary_model_name)
        if model_obj is not None:
            loaded_models[primary_model_name] = model_obj
            resolved_primary = primary_model_name
            log.info("Loaded primary model: %s", label)

    if resolved_primary is None:
        for fallback in MODEL_FALLBACK_CHAIN:
            model_obj, label = _load_model_file(models_dir, fallback)
            if model_obj is not None:
                loaded_models[fallback] = model_obj
                resolved_primary = fallback
                log.info("Loaded fallback model: %s", label)
                break

    if resolved_primary is None:
        log.error("No usable model found in bundle for agent %s", agent_id)
        return None

    patterns: dict = {}
    patterns_path = models_dir / "patterns.json"
    if patterns_path.exists():
        patterns = json.loads(patterns_path.read_text())
        log.info("Loaded patterns.json with %d entries", len(patterns))

    bundle = AgentModelBundle(
        agent_id=agent_id,
        bundle_id=bundle_id,
        version=version,
        minio_path=minio_path,
        models=loaded_models,
        preprocessor=preprocessor,
        meta=meta,
        feature_columns=feature_columns,
        primary_model=resolved_primary,
        patterns=patterns,
    )

    log.info(
        "Model bundle loaded for agent %s: primary=%s, models=%d, features=%d",
        agent_id, resolved_primary, len(loaded_models), len(feature_columns),
    )
    return bundle


def _evict_lru_if_needed() -> None:
    """Evict least-recently-used agent model if we exceed MAX_LOADED_MODELS."""
    while len(_agent_models) > MAX_LOADED_MODELS:
        evicted_id, evicted = _agent_models.popitem(last=False)
        log.info(
            "Evicted LRU model for agent %s (v%d) to stay under limit %d",
            evicted_id, evicted.version, MAX_LOADED_MODELS,
        )


async def _load_agent_bundle(agent_id: str) -> bool:
    """Load the latest approved bundle for a single agent. Returns True on success."""
    try:
        async with _session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT id, minio_path, primary_model, version
                    FROM model_bundles
                    WHERE agent_id = :agent_id AND status = 'approved'
                    ORDER BY version DESC
                    LIMIT 1
                """),
                {"agent_id": agent_id},
            )
            row = result.fetchone()
            if not row:
                log.warning("No approved bundle for agent %s", agent_id)
                return False

            bundle_id, minio_path, _primary_model, version = str(row[0]), row[1], row[2], row[3]
            log.info("Found approved bundle for agent %s: id=%s path=%s v%d", agent_id, bundle_id, minio_path, version)
    except Exception as exc:
        log.error("Failed to query model_bundles for agent %s: %s", agent_id, exc)
        return False

    try:
        models_dir = _download_and_extract_bundle(minio_path)
        bundle = load_models_from_directory(models_dir, agent_id, bundle_id, version, minio_path)
        if bundle is None:
            return False
        _agent_models[agent_id] = bundle
        _agent_models.move_to_end(agent_id)
        _evict_lru_if_needed()
        return True
    except Exception as exc:
        log.error("Failed to download/load bundle for agent %s: %s", agent_id, exc)
        return False


async def _load_all_approved_bundles() -> int:
    """Load the latest approved bundle for every agent. Returns count of agents loaded."""
    loaded_count = 0
    try:
        async with _session_factory() as session:
            result = await session.execute(
                text("""
                    SELECT DISTINCT ON (agent_id)
                        id, agent_id, minio_path, primary_model, version
                    FROM model_bundles
                    WHERE status = 'approved'
                    ORDER BY agent_id, version DESC
                """)
            )
            rows = result.fetchall()
            if not rows:
                log.warning("No approved model bundles found in database")
                return 0

            log.info("Found %d approved agent bundles to load", len(rows))
    except Exception as exc:
        log.error("Failed to query model_bundles: %s", exc)
        return 0

    for row in rows:
        bundle_id, agent_id, minio_path, _primary_model, version = (
            str(row[0]), str(row[1]), row[2], row[3], row[4],
        )
        try:
            models_dir = _download_and_extract_bundle(minio_path)
            bundle = load_models_from_directory(models_dir, agent_id, bundle_id, version, minio_path)
            if bundle is not None:
                _agent_models[agent_id] = bundle
                _agent_models.move_to_end(agent_id)
                loaded_count += 1
        except Exception as exc:
            log.error("Failed to load bundle for agent %s: %s", agent_id, exc)

    _evict_lru_if_needed()
    log.info("Loaded models for %d / %d agents", loaded_count, len(rows))
    return loaded_count


def _prepare_feature_vector(
    bundle: AgentModelBundle,
    feature_store_features: dict[str, Any],
    signal_features: dict[str, Any],
) -> pd.DataFrame:
    """Merge Feature Store features with signal features, align to model columns, impute + scale."""
    merged = {**feature_store_features, **signal_features}

    feature_cols = bundle.feature_columns
    if feature_cols:
        row = {col: merged.get(col, np.nan) for col in feature_cols}
        df = pd.DataFrame([row], columns=feature_cols)
    else:
        numeric = {k: v for k, v in merged.items() if isinstance(v, (int, float, np.integer, np.floating))}
        df = pd.DataFrame([numeric])

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    imputer = bundle.preprocessor.get("imputer")
    if imputer is not None:
        try:
            cols = df.columns.tolist()
            df = pd.DataFrame(imputer.transform(df), columns=cols)
        except Exception as exc:
            log.warning("Imputer failed, filling NaN with 0: %s", exc)
            df = df.fillna(0)
    else:
        df = df.fillna(0)

    scaler = bundle.preprocessor.get("scaler")
    if scaler is not None:
        try:
            cols = df.columns.tolist()
            df = pd.DataFrame(scaler.transform(df), columns=cols)
        except Exception as exc:
            log.warning("Scaler failed, using unscaled features: %s", exc)

    return df


def _run_prediction(bundle: AgentModelBundle, df: pd.DataFrame) -> tuple[str, float, str]:
    """Run the primary model for an agent and return (prediction, confidence, reasoning)."""
    primary_name = bundle.primary_model
    if primary_name is None:
        raise RuntimeError("Bundle has no primary model set")

    model = bundle.models.get(primary_name)
    if model is None:
        raise RuntimeError(f"Primary model '{primary_name}' not loaded")

    if isinstance(model, bytes):
        raise RuntimeError(f"Model '{primary_name}' is raw bytes (PyTorch) — not yet supported for inference")

    probas = None
    try:
        if hasattr(model, "predict_proba"):
            probas = model.predict_proba(df)
            pred_idx = int(np.argmax(probas[0]))
        else:
            raw = model.predict(df)
            pred_idx = int(raw[0]) if hasattr(raw[0], "__int__") else (1 if raw[0] else 0)
    except Exception as exc:
        raise RuntimeError(f"Model prediction failed: {exc}") from exc

    prediction = "TRADE" if pred_idx == 1 else "SKIP"

    if probas is not None:
        confidence = float(np.max(probas[0]))
    else:
        confidence = 0.5

    pattern_notes = []
    if bundle.patterns:
        for pat_name, pat_info in bundle.patterns.items():
            if isinstance(pat_info, dict) and pat_info.get("active"):
                pattern_notes.append(pat_name)

    reasoning_parts = [f"{primary_name} predicted {prediction} with {confidence:.1%} confidence"]
    if pattern_notes:
        reasoning_parts.append(f"Active patterns: {', '.join(pattern_notes[:5])}")
    reasoning = ". ".join(reasoning_parts)

    return prediction, round(confidence, 4), reasoning


async def _log_prediction(
    agent_id: str,
    bundle_id: str | None,
    ticker: str,
    features_snapshot: dict[str, Any],
    prediction: str,
    confidence: float,
    reasoning: str,
) -> None:
    """Insert a row into the predictions table."""
    try:
        async with _session_factory() as session:
            await session.execute(
                text("""
                    INSERT INTO predictions (agent_id, model_bundle_id, ticker, features_snapshot,
                                             prediction, confidence, reasoning, predicted_at)
                    VALUES (:agent_id, :bundle_id, :ticker, :features, :prediction, :confidence,
                            :reasoning, :predicted_at)
                """),
                {
                    "agent_id": agent_id,
                    "bundle_id": bundle_id,
                    "ticker": ticker.upper(),
                    "features": json.dumps(features_snapshot, default=str),
                    "prediction": prediction,
                    "confidence": confidence,
                    "reasoning": reasoning,
                    "predicted_at": datetime.now(timezone.utc),
                },
            )
            await session.commit()
    except Exception as exc:
        log.error("Failed to log prediction: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _redis
    try:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
        await _redis.ping()
        log.info("Connected to Redis")
    except Exception as exc:
        log.warning("Redis unavailable, running without cache: %s", exc)
        _redis = None

    loaded = await _load_all_approved_bundles()
    if loaded == 0:
        log.warning("No models loaded at startup — service degraded until POST /models/reload")
    else:
        log.info("Startup complete: %d agent model(s) loaded", loaded)

    yield

    if _redis:
        await _redis.aclose()
    await _engine.dispose()


app = FastAPI(title="Phoenix Inference Service", version="2.0.0", lifespan=lifespan)


@app.post("/predict", response_model=PredictResponse)
async def predict(req: PredictRequest):
    ticker = req.ticker.upper()

    try:
        agent_uuid = uuid.UUID(req.agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid agent_id: {req.agent_id}")

    agent_id_str = str(agent_uuid)
    bundle = _agent_models.get(agent_id_str)
    if bundle is None:
        return PredictResponse(
            prediction="SKIP",
            confidence=0.0,
            reasoning="no_model_for_agent",
            model="none",
            feature_count=0,
        )

    bundle.last_used = datetime.now(timezone.utc)
    _agent_models.move_to_end(agent_id_str)

    feature_store_features: dict[str, Any] = {}
    try:
        async with _session_factory() as session:
            fs = FeatureStoreClient(session, _redis)
            feature_store_features = await fs.read_feature_view(ticker)
    except Exception as exc:
        log.warning("Feature Store read failed for %s, proceeding with signal features only: %s", ticker, exc)

    merged = {**feature_store_features, **req.signal_features}
    df = _prepare_feature_vector(bundle, feature_store_features, req.signal_features)
    prediction, confidence, reasoning = _run_prediction(bundle, df)

    await _log_prediction(
        agent_id=agent_id_str,
        bundle_id=bundle.bundle_id,
        ticker=ticker,
        features_snapshot=merged,
        prediction=prediction,
        confidence=confidence,
        reasoning=reasoning,
    )

    return PredictResponse(
        prediction=prediction,
        confidence=confidence,
        reasoning=reasoning,
        model=bundle.primary_model or "unknown",
        feature_count=df.shape[1],
    )


@app.get("/models")
async def list_models():
    agents = []
    for aid, bundle in _agent_models.items():
        model_names = list(bundle.models.keys())
        agents.append({
            "agent_id": aid,
            "bundle_id": bundle.bundle_id,
            "version": bundle.version,
            "primary_model": bundle.primary_model,
            "models": model_names,
            "feature_count": len(bundle.feature_columns),
            "loaded_at": bundle.loaded_at.isoformat(),
            "last_used": bundle.last_used.isoformat(),
        })
    return {
        "loaded_agents": len(agents),
        "max_loaded_models": MAX_LOADED_MODELS,
        "agents": agents,
    }


@app.post("/models/reload")
async def reload_models(agent_id: str | None = Query(default=None)):
    if agent_id is not None:
        try:
            agent_uuid = uuid.UUID(agent_id)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid agent_id: {agent_id}")
        success = await _load_agent_bundle(str(agent_uuid))
        if not success:
            raise HTTPException(status_code=404, detail=f"No approved bundle found for agent {agent_id}")
        bundle = _agent_models[str(agent_uuid)]
        return {
            "status": "reloaded",
            "agent_id": str(agent_uuid),
            "primary_model": bundle.primary_model,
            "version": bundle.version,
            "loaded_at": bundle.loaded_at.isoformat(),
        }

    loaded = await _load_all_approved_bundles()
    if loaded == 0:
        raise HTTPException(status_code=404, detail="No approved model bundles found or load failed")
    return {
        "status": "reloaded",
        "agents_loaded": loaded,
        "total_loaded": len(_agent_models),
    }


@app.get("/health")
async def health():
    has_models = len(_agent_models) > 0
    return {
        "status": "ready" if has_models else "no_model",
        "service": "phoenix-inference-service",
        "model_loaded": has_models,
        "loaded_agents": len(_agent_models),
        "max_loaded_models": MAX_LOADED_MODELS,
        "agent_ids": list(_agent_models.keys()),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8045)

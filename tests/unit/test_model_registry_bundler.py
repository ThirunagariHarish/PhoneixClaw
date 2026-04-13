"""Unit tests for shared.model_registry.bundler — bundle create/extract/validate."""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest

from shared.model_registry.bundler import (
    CRITICAL_FILES,
    REQUIRED_FILES,
    _infer_feature_group,
    create_bundle,
    extract_bundle,
)


@pytest.fixture()
def model_dir(tmp_path: Path) -> Path:
    """Create a minimal valid model directory."""
    d = tmp_path / "model_src"
    d.mkdir()
    for f in REQUIRED_FILES | CRITICAL_FILES:
        (d / f).write_text("{}" if f.endswith(".json") else "binary")

    meta = {
        "feature_names": ["sma_20", "rsi_14", "sentiment_score", "vix_close", "iv_rank", "close"],
        "model_type": "xgboost",
    }
    (d / "meta.json").write_text(json.dumps(meta))
    (d / "feature_names.json").write_text(json.dumps(meta["feature_names"]))
    return d


@pytest.fixture()
def incomplete_dir(tmp_path: Path) -> Path:
    """Model directory missing critical files."""
    d = tmp_path / "incomplete"
    d.mkdir()
    (d / "best_model.json").write_text("{}")
    (d / "meta.json").write_text("{}")
    (d / "feature_names.json").write_text("[]")
    return d


class TestCreateBundle:
    def test_creates_tar_gz(self, model_dir: Path, tmp_path: Path):
        out = tmp_path / "out" / "bundle.tar.gz"
        result = create_bundle(model_dir, out)

        assert result == out
        assert out.exists()
        assert tarfile.is_tarfile(out)

    def test_tar_contains_all_files(self, model_dir: Path, tmp_path: Path):
        out = tmp_path / "bundle.tar.gz"
        create_bundle(model_dir, out)

        with tarfile.open(out, "r:gz") as tar:
            names = set(tar.getnames())

        for f in REQUIRED_FILES | CRITICAL_FILES:
            assert f in names

        assert "feature_schema.json" in names

    def test_generates_feature_schema(self, model_dir: Path, tmp_path: Path):
        out = tmp_path / "bundle.tar.gz"
        create_bundle(model_dir, out)

        schema_path = model_dir / "feature_schema.json"
        assert schema_path.exists()
        schema = json.loads(schema_path.read_text())
        assert "technical" in schema
        assert "sentiment" in schema
        assert "market_context" in schema
        assert "options" in schema

    def test_raises_on_missing_source(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            create_bundle(tmp_path / "nonexistent", tmp_path / "out.tar.gz")

    def test_raises_on_missing_critical_files(self, incomplete_dir: Path, tmp_path: Path):
        with pytest.raises(ValueError, match="Missing required model files"):
            create_bundle(incomplete_dir, tmp_path / "out.tar.gz")


class TestExtractBundle:
    def test_extracts_files(self, model_dir: Path, tmp_path: Path):
        bundle = tmp_path / "bundle.tar.gz"
        create_bundle(model_dir, bundle)

        dest = tmp_path / "extracted"
        extract_bundle(bundle, dest)

        for f in REQUIRED_FILES | CRITICAL_FILES:
            assert (dest / f).exists()

    def test_creates_dest_dir(self, model_dir: Path, tmp_path: Path):
        bundle = tmp_path / "bundle.tar.gz"
        create_bundle(model_dir, bundle)

        dest = tmp_path / "new" / "nested" / "dir"
        extract_bundle(bundle, dest)
        assert dest.exists()


class TestInferFeatureGroup:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("sma_20", "technical"),
            ("ema_50", "technical"),
            ("rsi_14", "technical"),
            ("macd_signal", "technical"),
            ("bb_upper", "technical"),
            ("atr_14", "technical"),
            ("volume_ratio", "technical"),
            ("sentiment_score", "sentiment"),
            ("news_positive", "sentiment"),
            ("vix_close", "market_context"),
            ("spy_return_5d", "market_context"),
            ("sector_momentum", "market_context"),
            ("market_breadth", "market_context"),
            ("iv_rank", "options"),
            ("option_volume", "options"),
            ("put_call_ratio", "options"),
            ("gamma_exposure", "options"),
            ("close", "market_data"),
            ("high", "market_data"),
            ("unknown_feature", "market_data"),
        ],
    )
    def test_mapping(self, name: str, expected: str):
        assert _infer_feature_group(name) == expected

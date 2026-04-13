"""Bundle packaging utilities — create and extract model tar.gz archives.

Ensures critical files (imputer.pkl, scaler.pkl) that were previously lost
during shutil.copytree are always included. Also generates feature_schema.json
from meta.json to map feature columns to Feature Store groups.
"""

from __future__ import annotations

import json
import logging
import tarfile
from pathlib import Path

log = logging.getLogger(__name__)

REQUIRED_FILES = {"best_model.json", "meta.json", "feature_names.json"}
CRITICAL_FILES = {"imputer.pkl", "scaler.pkl"}


def create_bundle(source_dir: Path, output_path: Path) -> Path:
    """Package model artifacts from source_dir into a tar.gz at output_path.

    Validates that all required + critical files exist, generates
    feature_schema.json from meta.json, then tars everything.
    """
    _validate_source_dir(source_dir)
    _generate_feature_schema(source_dir)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tarfile.open(output_path, "w:gz") as tar:
        for item in sorted(source_dir.iterdir()):
            tar.add(item, arcname=item.name)
            log.debug("Added to bundle: %s", item.name)

    log.info("Created bundle %s from %s (%d bytes)", output_path, source_dir, output_path.stat().st_size)
    return output_path


def extract_bundle(bundle_path: Path, dest_dir: Path) -> Path:
    """Extract a tar.gz bundle into dest_dir. Returns dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)

    with tarfile.open(bundle_path, "r:gz") as tar:
        try:
            tar.extractall(path=dest_dir, filter="data")
        except TypeError:
            tar.extractall(path=dest_dir)  # noqa: S202

    log.info("Extracted bundle %s to %s", bundle_path, dest_dir)
    return dest_dir


def _validate_source_dir(source_dir: Path) -> None:
    """Raise ValueError if required or critical files are missing."""
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Source directory does not exist: {source_dir}")

    all_required = REQUIRED_FILES | CRITICAL_FILES
    missing = {f for f in all_required if not (source_dir / f).exists()}
    if missing:
        raise ValueError(f"Missing required model files in {source_dir}: {sorted(missing)}")


def _generate_feature_schema(source_dir: Path) -> None:
    """Build feature_schema.json mapping feature columns to Feature Store groups.

    Reads meta.json for the feature list and uses naming conventions to
    assign each feature to a group (technical, sentiment, market_context,
    options, market_data).
    """
    meta_path = source_dir / "meta.json"
    if not meta_path.exists():
        return

    meta = json.loads(meta_path.read_text())
    feature_names: list[str] = meta.get("feature_names", [])
    if not feature_names:
        fn_path = source_dir / "feature_names.json"
        if fn_path.exists():
            feature_names = json.loads(fn_path.read_text())

    if not feature_names:
        return

    schema: dict[str, list[str]] = {}
    for name in feature_names:
        group = _infer_feature_group(name)
        schema.setdefault(group, []).append(name)

    schema_path = source_dir / "feature_schema.json"
    schema_path.write_text(json.dumps(schema, indent=2))
    log.info("Generated feature_schema.json with %d features across %d groups", len(feature_names), len(schema))


_GROUP_PREFIXES = {
    "sma_": "technical",
    "ema_": "technical",
    "rsi": "technical",
    "macd": "technical",
    "bb_": "technical",
    "atr": "technical",
    "adx": "technical",
    "stoch": "technical",
    "obv": "technical",
    "vwap": "technical",
    "volume_": "technical",
    "vol_": "technical",
    "sentiment": "sentiment",
    "news_": "sentiment",
    "vix": "market_context",
    "spy_": "market_context",
    "sector_": "market_context",
    "market_": "market_context",
    "corr_": "market_context",
    "iv_": "options",
    "option_": "options",
    "put_call": "options",
    "gamma": "options",
    "delta": "options",
    "oi_": "options",
    "open_interest": "options",
}


def _infer_feature_group(feature_name: str) -> str:
    lower = feature_name.lower()
    for prefix, group in _GROUP_PREFIXES.items():
        if lower.startswith(prefix):
            return group
    return "market_data"

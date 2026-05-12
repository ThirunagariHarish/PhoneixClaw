"""Feature computation wrapper — imports and calls enrich_trade from backtesting pipeline.

This module reuses the existing feature computation logic without duplication.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add repo root to sys.path so we can import from agents/backtesting/tools
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Import the existing feature computation functions
from agents.backtesting.tools.enrich import enrich_trade  # noqa: E402


def compute_features_for_trade(trade_row: dict, cache: dict) -> dict:
    """Compute ~200 features for a single trade using the existing enrich_trade function.

    Args:
        trade_row: Dict with keys: id, ticker, side, entry_price, entry_time,
                   target_price, stop_loss, channel_id, author_name, raw_message, etc.
        cache: Shared cache dict for yfinance data, sentiment classifier, etc.

    Returns:
        Dict of feature_name -> value, JSON-serializable
    """
    import pandas as pd

    # Convert dict to pd.Series (enrich_trade expects pd.Series)
    row_series = pd.Series(trade_row)

    # Call the existing function
    features = enrich_trade(row_series, cache)

    # enrich_trade returns a dict — ensure all values are JSON-serializable
    # (numpy types need conversion)
    return _sanitize_for_json(features)


def _sanitize_for_json(features: dict) -> dict:
    """Convert numpy types to native Python types for JSON serialization."""
    import numpy as np

    sanitized = {}
    for key, value in features.items():
        if isinstance(value, (np.integer, np.int64, np.int32)):
            sanitized[key] = int(value)
        elif isinstance(value, (np.floating, np.float64, np.float32)):
            # Convert NaN to None for JSON
            sanitized[key] = None if np.isnan(value) else float(value)
        elif isinstance(value, np.ndarray):
            sanitized[key] = value.tolist()
        elif value is None or isinstance(value, (str, int, float, bool, list, dict)):
            sanitized[key] = value
        else:
            # Fallback: convert to string
            sanitized[key] = str(value)

    return sanitized

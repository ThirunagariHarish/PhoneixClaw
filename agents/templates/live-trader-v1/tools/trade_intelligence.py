"""Trade-intelligence loader — single source of truth for learned decision heads.

Used by decision_engine.py. Lazy-loads any of the following artifacts from the
agent's `models/` directory if they exist:

    stop_loss_model.pkl       — T3: SL quantile regressor (label = MAE/ATR14)
    profit_target_model.pkl   — T3: TP quantile regressor (label = MFE/ATR14)
    pnl_win_model.pkl         — T2: E[pnl | win] regressor
    pnl_loss_model.pkl        — T2: E[loss | loss] regressor
    entry_buffer_model.pkl    — T5: slippage regressor
    fillability_model.pkl     — T5: p(fill_60s) classifier
    exit_timing_model.pkl     — T4: hold-minutes regressor
    exit_bucket_model.pkl     — T4: 5-class exit bucket classifier
    regime_calibration.json   — T10: per-regime {intercept, slope} dict
    kelly.json                — T7: {"kelly_fraction": float}
    bias_multipliers.json     — T11: {"sl_bias": .., "tp_bias": .., "slip_bias": ..}

Every missing artifact falls back to sensible defaults so the system never crashes
because a head hasn't been trained yet.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

log = logging.getLogger(__name__)

# Clamps prevent a crazy model prediction from escaping into risk chain
SL_MULT_CLAMP = (0.8, 4.0)
TP_MULT_CLAMP = (1.2, 6.0)
SLIP_BPS_CLAMP = (-30.0, 30.0)
KELLY_CLAMP = (0.0, 1.0)

# Defaults if no model trained
DEFAULT_SL_MULT = 2.0
DEFAULT_TP_MULT = 3.0
DEFAULT_KELLY_FRACTION = 0.25
DEFAULT_EV_THRESHOLD = 0.0


def _clamp(x: float, lo: float, hi: float) -> float:
    if not np.isfinite(x):
        return (lo + hi) / 2
    return max(lo, min(hi, float(x)))


class TradeIntelligence:
    """Lazily-loaded bundle of all learned trade-decision heads."""

    def __init__(self, models_dir: str | Path | None = None):
        self.models_dir: Path | None = Path(models_dir) if models_dir else None
        self._cache: dict[str, Any] = {}
        self._loaded = False

    # --- loader plumbing ---------------------------------------------------
    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.models_dir or not self.models_dir.exists():
            return
        try:
            import joblib
        except ImportError:
            log.warning("joblib not available — intelligence heads disabled")
            return

        pkl_heads = {
            "sl": "stop_loss_model.pkl",
            "tp": "profit_target_model.pkl",
            "pnl_win": "pnl_win_model.pkl",
            "pnl_loss": "pnl_loss_model.pkl",
            "entry_buffer": "entry_buffer_model.pkl",
            "fillability": "fillability_model.pkl",
            "exit_time": "exit_timing_model.pkl",
            "exit_bucket": "exit_bucket_model.pkl",
        }
        for key, filename in pkl_heads.items():
            path = self.models_dir / filename
            if path.exists():
                try:
                    self._cache[key] = joblib.load(path)
                    log.info("[intelligence] loaded %s", filename)
                except Exception as exc:
                    log.warning("[intelligence] failed to load %s: %s", filename, exc)

        json_heads = {
            "regime_cal": "regime_calibration.json",
            "kelly": "kelly.json",
            "bias": "bias_multipliers.json",
            "ev": "ev_threshold.json",
        }
        for key, filename in json_heads.items():
            path = self.models_dir / filename
            if path.exists():
                try:
                    self._cache[key] = json.loads(path.read_text())
                except Exception as exc:
                    log.warning("[intelligence] failed to load %s: %s", filename, exc)

    # --- feature vector construction ---------------------------------------
    @staticmethod
    def _feature_vector(enriched: dict, feature_names: list[str] | None) -> np.ndarray | None:
        """Align enriched dict into the same feature order the trainers used."""
        if not feature_names:
            return None
        row = [float(enriched.get(name, np.nan)) for name in feature_names]
        arr = np.array(row, dtype=np.float32).reshape(1, -1)
        # Impute NaNs with zeros — trainers used median imputation but at inference
        # time any missing feature is just zero-in-the-scaled space (~median).
        arr = np.nan_to_num(arr, nan=0.0, posinf=0.0, neginf=0.0)
        return arr

    # --- heads -------------------------------------------------------------
    def predict_sl_tp_multiples(self, enriched: dict,
                                feature_names: list[str] | None) -> tuple[float, float]:
        """T3: returns (sl_mult, tp_mult) in ATR units, with clamps + bias."""
        self._load()
        sl_mult = DEFAULT_SL_MULT
        tp_mult = DEFAULT_TP_MULT
        feats = self._feature_vector(enriched, feature_names)
        if feats is not None:
            sl_model = self._cache.get("sl")
            tp_model = self._cache.get("tp")
            try:
                if sl_model is not None:
                    sl_mult = float(sl_model.predict(feats)[0])
            except Exception as exc:
                log.debug("[intelligence] sl predict failed: %s", exc)
            try:
                if tp_model is not None:
                    tp_mult = float(tp_model.predict(feats)[0])
            except Exception as exc:
                log.debug("[intelligence] tp predict failed: %s", exc)

        bias = self._cache.get("bias") or {}
        sl_mult *= float(bias.get("sl_bias", 1.0))
        tp_mult *= float(bias.get("tp_bias", 1.0))
        return _clamp(sl_mult, *SL_MULT_CLAMP), _clamp(tp_mult, *TP_MULT_CLAMP)

    def predict_pnl(self, enriched: dict,
                    feature_names: list[str] | None) -> tuple[float, float]:
        """T2: returns (E[pnl|win], E[loss|loss]) both in decimal fractions (0.04 = 4%)."""
        self._load()
        feats = self._feature_vector(enriched, feature_names)
        e_win, e_loss = 0.04, -0.03  # defaults
        if feats is None:
            return e_win, e_loss
        try:
            mw = self._cache.get("pnl_win")
            if mw is not None:
                e_win = float(mw.predict(feats)[0])
        except Exception:
            pass
        try:
            ml = self._cache.get("pnl_loss")
            if ml is not None:
                e_loss = float(ml.predict(feats)[0])
        except Exception:
            pass
        # sanity: win ≥ 0, loss ≤ 0
        e_win = max(0.001, e_win)
        e_loss = min(-0.001, e_loss)
        return e_win, e_loss

    def ev_threshold(self) -> float:
        """T2: EV gate threshold — manifest-configured, default 0."""
        self._load()
        ev = self._cache.get("ev") or {}
        return float(ev.get("ev_threshold", DEFAULT_EV_THRESHOLD))

    def kelly_fraction(self) -> float:
        """T7: fraction of full Kelly to apply (backtest-calibrated)."""
        self._load()
        k = self._cache.get("kelly") or {}
        return _clamp(float(k.get("kelly_fraction", DEFAULT_KELLY_FRACTION)), *KELLY_CLAMP)

    def position_pct_kelly(self, p_win: float, e_win: float, e_loss: float,
                           max_pct: float) -> float:
        """T7: fractional Kelly sizing. e_win >0, e_loss <0."""
        p_win = max(0.0, min(1.0, p_win))
        p_loss = 1.0 - p_win
        edge = p_win * e_win + p_loss * e_loss
        var = p_win * e_win ** 2 + p_loss * e_loss ** 2 - edge ** 2
        if var <= 1e-9 or edge <= 0:
            return 0.0
        kelly_f = edge / var
        return float(min(max_pct, self.kelly_fraction() * kelly_f * max_pct))

    def predict_entry_slippage_bps(self, enriched: dict,
                                   feature_names: list[str] | None) -> float:
        """T5: returns predicted slippage in basis points, clamped."""
        self._load()
        feats = self._feature_vector(enriched, feature_names)
        slip = 0.0
        if feats is not None:
            m = self._cache.get("entry_buffer")
            try:
                if m is not None:
                    slip = float(m.predict(feats)[0])
            except Exception:
                pass
        bias = self._cache.get("bias") or {}
        slip *= float(bias.get("slip_bias", 1.0))
        return _clamp(slip, *SLIP_BPS_CLAMP)

    def predict_fill_probability(self, enriched: dict,
                                 feature_names: list[str] | None) -> float:
        """T5: p(order fills within 60s). Defaults to 0.85 when no model."""
        self._load()
        feats = self._feature_vector(enriched, feature_names)
        if feats is None:
            return 0.85
        m = self._cache.get("fillability")
        if m is None:
            return 0.85
        try:
            if hasattr(m, "predict_proba"):
                return float(m.predict_proba(feats)[0, 1])
            return float(m.predict(feats)[0])
        except Exception:
            return 0.85

    def predict_exit_bucket(self, enriched: dict,
                            feature_names: list[str] | None) -> tuple[str, float]:
        """T4: returns (bucket_label, expected_hold_minutes)."""
        self._load()
        labels = ["lt_5m", "5_30m", "30m_2h", "2h_eod", "next_day"]
        default = ("5_30m", 20.0)
        feats = self._feature_vector(enriched, feature_names)
        if feats is None:
            return default
        bucket = default[0]
        hold = default[1]
        try:
            m = self._cache.get("exit_bucket")
            if m is not None:
                idx = int(m.predict(feats)[0])
                bucket = labels[max(0, min(len(labels) - 1, idx))]
        except Exception:
            pass
        try:
            m = self._cache.get("exit_time")
            if m is not None:
                hold = float(m.predict(feats)[0])
        except Exception:
            pass
        return bucket, hold

    def apply_regime_calibration(self, raw_confidence: float, regime: str | None) -> float:
        """T10: apply per-regime logistic recalibration if available."""
        self._load()
        if not regime:
            return raw_confidence
        cal = (self._cache.get("regime_cal") or {}).get(regime)
        if not cal:
            return raw_confidence
        try:
            intercept = float(cal.get("intercept", 0.0))
            slope = float(cal.get("slope", 1.0))
            # logistic remap
            x = intercept + slope * raw_confidence
            return float(1.0 / (1.0 + np.exp(-x)))
        except Exception:
            return raw_confidence


_singleton: TradeIntelligence | None = None


def get_intelligence(models_dir: str | Path | None = None) -> TradeIntelligence:
    """Return (and cache) a module-level TradeIntelligence instance."""
    global _singleton
    if _singleton is None or (models_dir and str(_singleton.models_dir) != str(models_dir)):
        _singleton = TradeIntelligence(models_dir or os.environ.get("PHOENIX_MODELS_DIR"))
    return _singleton

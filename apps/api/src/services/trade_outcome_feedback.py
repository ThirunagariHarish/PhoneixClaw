"""T11: Online bias-correction feedback loop.

Nightly job that reads `trade_outcomes_feedback` rows per agent, computes
rolling bias multipliers, and writes them into each agent's `bias_multipliers.json`
(which trade_intelligence.py already reads at inference time).

Rules (requires n >= 30 closed trades AND abs(bias - 1) > 0.1 to apply):
    sl_bias   = mean(actual_mae_atr / predicted_sl_mult)
    tp_bias   = mean(actual_mfe_atr / predicted_tp_mult)
    slip_bias = mean(actual_slip_bps / predicted_slip_bps)

Run from scheduler or via: python -m apps.api.src.services.trade_outcome_feedback
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

MIN_SAMPLES = 30
SIGNIFICANT_DEVIATION = 0.10  # 10%


async def compute_bias_multipliers(agent_id: str, *, days: int = 30) -> dict | None:
    """Return bias dict for an agent, or None if not enough data."""
    try:
        from sqlalchemy import text
        from shared.db.engine import get_session
    except Exception as exc:
        logger.warning("[feedback] DB unavailable: %s", exc)
        return None

    query = text("""
        SELECT predicted_sl_mult, actual_mae_atr,
               predicted_tp_mult, actual_mfe_atr,
               predicted_slip_bps, actual_slip_bps
        FROM trade_outcomes_feedback
        WHERE agent_id = :agent_id
          AND closed_at >= NOW() - (:days || ' days')::interval
    """)
    rows = []
    async for session in get_session():
        result = await session.execute(query, {"agent_id": agent_id, "days": days})
        rows = list(result.all())
        break

    if len(rows) < MIN_SAMPLES:
        return None

    def _mean_ratio(numer_idx: int, denom_idx: int) -> float | None:
        ratios = []
        for r in rows:
            n = r[numer_idx]
            d = r[denom_idx]
            if n is None or d is None or d == 0:
                continue
            ratios.append(float(n) / float(d))
        if len(ratios) < MIN_SAMPLES:
            return None
        return sum(ratios) / len(ratios)

    sl_ratio = _mean_ratio(1, 0)  # actual_MAE / predicted_SL
    tp_ratio = _mean_ratio(3, 2)  # actual_MFE / predicted_TP
    slip_ratio = _mean_ratio(5, 4)  # actual_slip / predicted_slip

    bias: dict[str, float] = {}
    if sl_ratio is not None and abs(sl_ratio - 1.0) > SIGNIFICANT_DEVIATION:
        bias["sl_bias"] = round(sl_ratio, 3)
    if tp_ratio is not None and abs(tp_ratio - 1.0) > SIGNIFICANT_DEVIATION:
        bias["tp_bias"] = round(tp_ratio, 3)
    if slip_ratio is not None and abs(slip_ratio - 1.0) > SIGNIFICANT_DEVIATION:
        bias["slip_bias"] = round(slip_ratio, 3)

    return bias or None


async def update_all_agents(data_root: str | None = None) -> dict:
    """Walk agent dirs and refresh each agent's bias_multipliers.json."""
    root = Path(data_root or os.environ.get("PHOENIX_AGENTS_DIR", "data/agents/live"))
    summary: dict = {"processed": 0, "updated": 0, "agents": {}}
    if not root.exists():
        return summary

    for agent_dir in root.iterdir():
        if not agent_dir.is_dir():
            continue
        agent_id = agent_dir.name
        summary["processed"] += 1
        try:
            bias = await compute_bias_multipliers(agent_id)
        except Exception as exc:
            logger.exception("[feedback] %s bias compute failed: %s", agent_id, exc)
            continue
        if not bias:
            continue

        models_dir = agent_dir / "models"
        models_dir.mkdir(parents=True, exist_ok=True)
        out = models_dir / "bias_multipliers.json"
        try:
            existing = json.loads(out.read_text()) if out.exists() else {}
        except Exception:
            existing = {}
        existing.update(bias)
        out.write_text(json.dumps(existing, indent=2))
        summary["updated"] += 1
        summary["agents"][agent_id] = bias
        logger.info("[feedback] %s bias=%s", agent_id, bias)

    return summary


# Sync entrypoint for scheduler job + CLI
async def run_feedback_job() -> dict:
    return await update_all_agents()

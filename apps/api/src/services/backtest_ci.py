"""Backtest CI service — gate that validates pending improvements before activation.

Phase 0: Verifiable Alpha CI.
Every rule in ``agents.pending_improvements`` must pass a backtest CI check before
it can be activated.  For now, we proxy the check using the most recent completed
AgentBacktest for the agent (a TODO marks where per-rule backtesting will plug in).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.agent import Agent, AgentBacktest, AgentLog

# ---------------------------------------------------------------------------
# Thresholds — all rules must satisfy these to be eligible for activation
# ---------------------------------------------------------------------------

THRESHOLDS: dict[str, float] = {
    "sharpe_ratio": 0.8,
    "win_rate": 0.53,       # 53 %
    "max_drawdown": -0.15,  # max_drawdown is negative; -0.12 passes, -0.18 fails
    "profit_factor": 1.3,
    "min_trades": 15.0,
}

# 10 % miss on a *single* threshold → "borderline" instead of an outright "failed"
BORDERLINE_TOLERANCE = 0.10


class BacktestCIService:
    """Service that runs CI validation on pending improvement rules."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_ci_for_improvement(
        self,
        agent_id: uuid.UUID,
        improvement_id: str,
    ) -> dict[str, Any]:
        """Run CI validation for a single pending improvement.

        Looks up the most recent completed AgentBacktest for the agent and uses
        its metrics as a proxy for the rule's performance.

        TODO: Replace the AgentBacktest proxy with a per-rule backtest in a
              future phase once the rule-level backtesting pipeline is ready.

        Returns:
            The updated improvement dict with CI result fields added:
            ``backtest_passed``, ``backtest_status``, ``backtest_metrics``,
            ``backtest_run_at``, and ``backtest_thresholds_missed``.

        Raises:
            ValueError:    Agent not found.
            KeyError:      Improvement ID not found in pending_improvements.
            OverflowError: Pending improvements cap (50) exceeded.
        """
        session = self._session

        # 1. Load agent row
        result = await session.execute(select(Agent).where(Agent.id == agent_id))
        agent = result.scalar_one_or_none()
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")

        # 2. Locate the improvement inside pending_improvements.items
        pending: dict[str, Any] = agent.pending_improvements or {}
        items: list[dict[str, Any]] = (
            pending.get("items", []) if isinstance(pending, dict) else []
        )

        target_item: dict[str, Any] | None = next(
            (item for item in items if item.get("id") == improvement_id), None
        )
        if target_item is None:
            raise KeyError(
                f"Improvement '{improvement_id}' not found on agent {agent_id}"
            )

        # 3. Enforce cap of 50 pending improvements
        if len(items) > 50:
            raise OverflowError(
                f"Agent {agent_id} has {len(items)} pending improvements (cap is 50)"
            )

        # 4. Set "running" status immediately and persist
        target_item["backtest_status"] = "running"
        agent.pending_improvements = {**pending, "items": list(items)}
        await session.commit()

        # 5. Query the most recent *completed* AgentBacktest for this agent
        #    TODO (future phase): replace with a per-rule isolated backtest run.
        bt_result = await session.execute(
            select(AgentBacktest)
            .where(
                AgentBacktest.agent_id == agent_id,
                AgentBacktest.status == "COMPLETED",
            )
            .order_by(desc(AgentBacktest.created_at))
            .limit(1)
        )
        backtest: AgentBacktest | None = bt_result.scalar_one_or_none()

        # 6. Extract normalised metrics dict
        metrics = self._extract_metrics(backtest)

        # 7. Evaluate thresholds → status, passed flag, list of missed threshold names
        status, passed, missed = self._evaluate_thresholds(metrics)

        # 8. Update improvement item in-place with CI results
        now_iso = datetime.now(timezone.utc).isoformat()
        target_item.update(
            {
                "backtest_passed": passed,
                "backtest_status": status,
                "backtest_metrics": metrics,
                "backtest_run_at": now_iso,
                "backtest_thresholds_missed": missed,
            }
        )

        # 9. Persist final state back to agent row
        agent.pending_improvements = {**pending, "items": list(items)}
        agent.updated_at = datetime.now(timezone.utc)

        # 10. Write structured log entry for audit trail
        session.add(
            AgentLog(
                id=uuid.uuid4(),
                agent_id=agent_id,
                level="INFO",
                message=f"Backtest CI for improvement '{improvement_id}': {status}",
                context={
                    "improvement_id": improvement_id,
                    "backtest_status": status,
                    "thresholds_missed": missed,
                    "backtest_metrics": metrics,
                },
            )
        )
        await session.commit()

        return dict(target_item)

    # ------------------------------------------------------------------
    # Threshold evaluation helpers (pure, no I/O — easy to unit-test)
    # ------------------------------------------------------------------

    def _evaluate_thresholds(
        self, metrics: dict[str, Any]
    ) -> tuple[str, bool, list[str]]:
        """Evaluate all CI thresholds against the provided metrics dict.

        Decision matrix:
        - 0 failures            → "passed"  (backtest_passed=True)
        - 1 failure, borderline → "borderline" (backtest_passed=False)
        - 1 failure, NOT borderline OR 2+ failures → "failed" (backtest_passed=False)

        Returns:
            (status, passed, missed_thresholds) where:
            - status is "passed" | "borderline" | "failed"
            - passed is True only when status == "passed"
            - missed_thresholds is the list of threshold names that failed
        """
        checks: list[tuple[str, float, float]] = [
            (
                "sharpe_ratio",
                float(metrics.get("sharpe", 0.0)),
                THRESHOLDS["sharpe_ratio"],
            ),
            (
                "win_rate",
                float(metrics.get("win_rate", 0.0)),
                THRESHOLDS["win_rate"],
            ),
            (
                "max_drawdown",
                float(metrics.get("max_drawdown", 0.0)),
                THRESHOLDS["max_drawdown"],
            ),
            (
                "profit_factor",
                float(metrics.get("profit_factor", 0.0)),
                THRESHOLDS["profit_factor"],
            ),
            (
                "min_trades",
                float(metrics.get("trade_count", 0)),
                THRESHOLDS["min_trades"],
            ),
        ]

        missed: list[str] = []
        borderline_count = 0

        for name, actual, threshold in checks:
            if actual < threshold:
                missed.append(name)
                if self._is_borderline(name, actual, threshold):
                    borderline_count += 1

        fail_count = len(missed)

        if fail_count == 0:
            return "passed", True, []
        if fail_count == 1 and borderline_count == 1:
            # Exactly one threshold failed and it is within 10 % of the limit
            return "borderline", False, missed
        # 2+ failures OR single failure that is not borderline
        return "failed", False, missed

    def _is_borderline(
        self, metric_name: str, actual: float, threshold: float
    ) -> bool:
        """Return True if ``actual`` is within BORDERLINE_TOLERANCE below ``threshold``.

        Works uniformly for both positive-target metrics (sharpe, win_rate,
        profit_factor, min_trades) and the negative-target metric (max_drawdown),
        because the pass condition is always ``actual >= threshold``.

        A "miss" of up to ``abs(threshold) * BORDERLINE_TOLERANCE`` is treated as
        borderline rather than an outright failure.

        Examples:
            threshold=0.8, actual=0.76 → miss=0.04, tol=0.08 → borderline ✓
            threshold=0.8, actual=0.68 → miss=0.12, tol=0.08 → NOT borderline ✓
            threshold=-0.15, actual=-0.165 → miss=0.015, tol=0.015 → borderline ✓
            threshold=-0.15, actual=-0.18  → miss=0.03, tol=0.015 → NOT borderline ✓
        """
        if actual >= threshold:
            return False  # passes — not borderline
        miss = threshold - actual          # always positive: how far below the bar
        tolerance = abs(threshold) * BORDERLINE_TOLERANCE
        return miss <= tolerance

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_metrics(backtest: AgentBacktest | None) -> dict[str, Any]:
        """Normalise an AgentBacktest row into the standard metrics dict.

        If no completed backtest exists, all values default to 0 / 0.0.
        """
        if backtest is None:
            return {
                "sharpe": 0.0,
                "win_rate": 0.0,
                "max_drawdown": 0.0,
                "profit_factor": 0.0,
                "trade_count": 0,
            }

        bt_metrics: dict[str, Any] = backtest.metrics or {}
        return {
            "sharpe": (
                float(backtest.sharpe_ratio)
                if backtest.sharpe_ratio is not None
                else float(bt_metrics.get("sharpe_ratio", 0.0))
            ),
            "win_rate": (
                float(backtest.win_rate)
                if backtest.win_rate is not None
                else float(bt_metrics.get("win_rate", 0.0))
            ),
            "max_drawdown": (
                float(backtest.max_drawdown)
                if backtest.max_drawdown is not None
                else float(bt_metrics.get("max_drawdown", 0.0))
            ),
            "profit_factor": float(bt_metrics.get("profit_factor", 0.0)),
            "trade_count": int(backtest.total_trades or 0),
        }

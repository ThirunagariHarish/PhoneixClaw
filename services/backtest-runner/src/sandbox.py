"""
Sandboxed backtest execution — runs user-provided strategy code
in an isolated subprocess with resource limits.

M2.7: Backtest runner sandbox.
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_LIMIT_MB = 512
DEFAULT_TIMEOUT_SECONDS = 120


@dataclass
class BacktestResult:
    total_trades: int = 0
    win_rate: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    total_return: float = 0.0
    equity_curve: list[float] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)


class BacktestSandbox:
    """Creates an isolated execution environment for backtesting strategies."""

    def __init__(
        self,
        memory_limit_mb: int = DEFAULT_MEMORY_LIMIT_MB,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ):
        self._memory_limit_mb = memory_limit_mb
        self._timeout_seconds = timeout_seconds

    def _build_runner_script(
        self, strategy_code: str, data_path: str, params: dict
    ) -> str:
        """Generate the script that executes inside the subprocess."""
        return textwrap.dedent(f"""\
            import json, sys, resource
            import pandas as pd

            resource.setrlimit(resource.RLIMIT_AS,
                               ({self._memory_limit_mb} * 1024 * 1024,
                                {self._memory_limit_mb} * 1024 * 1024))

            data = pd.read_parquet("{data_path}")
            params = json.loads('''{json.dumps(params)}''')

            # --- user strategy code injected below ---
            {textwrap.indent(strategy_code, "            ").strip()}
            # --- end user strategy code ---

            if "run" not in dir():
                print(json.dumps({{"error": "strategy must define a run(data, params) function"}}))
                sys.exit(1)

            result = run(data, params)
            print(json.dumps(result, default=str))
        """)

    def run(
        self,
        strategy_code: str,
        data: pd.DataFrame,
        params: dict | None = None,
    ) -> BacktestResult:
        """Execute strategy code in a sandboxed subprocess."""
        params = params or {}

        with tempfile.TemporaryDirectory(prefix="backtest_") as tmp:
            data_path = Path(tmp) / "data.parquet"
            script_path = Path(tmp) / "runner.py"

            data.to_parquet(data_path)
            script_content = self._build_runner_script(strategy_code, str(data_path), params)
            script_path.write_text(script_content)

            try:
                proc = subprocess.run(
                    [sys.executable, str(script_path)],
                    capture_output=True,
                    text=True,
                    timeout=self._timeout_seconds,
                    cwd=tmp,
                    env={"PATH": "", "HOME": tmp},
                )
            except subprocess.TimeoutExpired:
                logger.error("Backtest timed out after %ds", self._timeout_seconds)
                return BacktestResult(metrics={"error": "timeout"})

            if proc.returncode != 0:
                logger.error("Backtest subprocess failed: %s", proc.stderr[:500])
                return BacktestResult(metrics={"error": proc.stderr[:500]})

            try:
                raw = json.loads(proc.stdout)
            except json.JSONDecodeError:
                logger.error("Invalid JSON from backtest: %s", proc.stdout[:500])
                return BacktestResult(metrics={"error": "invalid_output"})

        return BacktestResult(
            total_trades=raw.get("total_trades", 0),
            win_rate=raw.get("win_rate", 0.0),
            sharpe_ratio=raw.get("sharpe_ratio", 0.0),
            max_drawdown=raw.get("max_drawdown", 0.0),
            total_return=raw.get("total_return", 0.0),
            equity_curve=raw.get("equity_curve", []),
            metrics=raw.get("metrics", {}),
        )

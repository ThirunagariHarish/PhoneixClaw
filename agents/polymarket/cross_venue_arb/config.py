"""Typed config loader for cross_venue_arb.

Kept tiny on purpose: this is a scaffold. The orchestrator agent loader
calls `load_config()` to discover the agent and its initial state.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@dataclass(frozen=True)
class CrossVenueArbConfig:
    name: str
    family: str
    version: str
    enabled: bool
    mode: str
    status: str
    secondary_venue: str
    min_edge_bps: int
    min_liquidity_usd: float
    max_notional_usd: float
    slippage_buffer_bps: int
    require_f9_tradeable_both_legs: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CrossVenueArbConfig":
        return cls(
            name=str(data["name"]),
            family=str(data["family"]),
            version=str(data["version"]),
            enabled=bool(data.get("enabled", False)),
            mode=str(data.get("mode", "paper")),
            status=str(data.get("status", "stopped")),
            secondary_venue=str(data.get("secondary_venue", "kalshi")),
            min_edge_bps=int(data.get("min_edge_bps", 150)),
            min_liquidity_usd=float(data.get("min_liquidity_usd", 5000)),
            max_notional_usd=float(data.get("max_notional_usd", 250)),
            slippage_buffer_bps=int(data.get("slippage_buffer_bps", 25)),
            require_f9_tradeable_both_legs=bool(
                data.get("require_f9_tradeable_both_legs", True)
            ),
        )


def load_config(path: Path | None = None) -> CrossVenueArbConfig:
    """Load and parse `config.yaml`.

    The orchestrator's agent loader uses this. Even when `enabled` is
    false, the loader still calls this so the agent appears in the
    registry in STOPPED state (Phase 9 DoD).
    """
    target = path or _CONFIG_PATH
    with target.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return CrossVenueArbConfig.from_dict(data)

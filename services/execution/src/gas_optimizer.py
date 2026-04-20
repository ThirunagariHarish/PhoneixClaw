"""
Dynamic Gas/Fee Optimizer — calculates optimal limit order price
based on spread, L2 depth, and time urgency.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Urgency(str, Enum):
    CAN_WAIT = "can_wait"      # Patient — optimize for best price
    NORMAL = "normal"          # Balanced
    NEED_FILL_NOW = "need_fill_now"  # Aggressive — prioritize fill speed


@dataclass
class L2Depth:
    """Order book depth snapshot."""
    bids: list[tuple[float, float]]  # (price, size)
    asks: list[tuple[float, float]]


class GasOptimizer:
    """
    Calculates optimal limit order price to save 0.5-1% slippage
    based on spread, L2 depth, and urgency.
    """

    def __init__(self, default_slippage_savings_pct: float = 0.75):
        self.default_savings = default_slippage_savings_pct

    def optimize(
        self,
        symbol: str,
        side: str,
        urgency: Urgency | str,
        current_bid: float,
        current_ask: float,
        l2_depth: L2Depth | None = None,
    ) -> float:
        """
        Return optimal limit price for the given side.
        - BUY: aim below mid to save slippage
        - SELL: aim above mid to save slippage
        """
        urgency = Urgency(urgency) if isinstance(urgency, str) else urgency
        spread = current_ask - current_bid
        mid = (current_bid + current_ask) / 2

        # Base savings: 0.5-1% of price depending on urgency
        if urgency == Urgency.CAN_WAIT:
            savings_pct = self.default_savings
        elif urgency == Urgency.NORMAL:
            savings_pct = self.default_savings * 0.6
        else:
            savings_pct = 0.25  # Need fill now — minimal savings, closer to market

        # Improvement = % of mid price, capped by half-spread (realistic fill)
        improvement = min(mid * (savings_pct / 100), spread * 0.5)

        # Adjust based on L2 depth if available
        depth_adjustment = 0.0
        if l2_depth and spread > 0:
            depth_adjustment = self._depth_adjustment(side, l2_depth, spread)

        if side.lower() in ("buy", "b"):
            optimal = current_ask - improvement - depth_adjustment
            optimal = max(optimal, current_bid)
        else:
            optimal = current_bid + improvement + depth_adjustment
            optimal = min(optimal, current_ask)

        logger.debug(
            "GasOptimizer %s %s: bid=%.2f ask=%.2f -> optimal=%.2f",
            symbol, side, current_bid, current_ask, optimal,
        )
        return round(optimal, 2)

    def _depth_adjustment(self, side: str, l2: L2Depth, spread: float) -> float:
        """
        Analyze L2 depth: thin book = less aggressive placement.
        Returns adjustment in price units (positive = more conservative).
        """
        if side.lower() in ("buy", "b"):
            levels = l2.asks
            # Thin asks = less room to improve, stay closer to market
            if not levels:
                return 0.0
            total_size = sum(s for _, s in levels[:5])
            if total_size < 100:
                return spread * 0.1  # Thin — be conservative
            return 0.0
        else:
            levels = l2.bids
            if not levels:
                return 0.0
            total_size = sum(s for _, s in levels[:5])
            if total_size < 100:
                return spread * 0.1
            return 0.0

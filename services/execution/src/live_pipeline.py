"""
Live trading pipeline — processes incoming messages through the intelligence
filter and creates trade intents for approved signals.

Flow:
1. Receive new message from a connected channel
2. Parse signal (buy/sell/close)
3. Apply intelligence rules from backtesting
4. If signal passes filters, create a TradeIntent
5. Run through risk chain
6. Execute via broker
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from shared.nlp.signal_parser import parse_signal

logger = logging.getLogger(__name__)


class IntelligenceFilter:
    """
    Applies learned rules from backtesting to filter incoming signals.
    Rules have weights: positive = take trade, negative = avoid.
    A combined score above threshold means the signal passes.
    """

    def __init__(self, rules: list[dict], threshold: float = 0.0):
        self.rules = rules
        self.threshold = threshold

    def evaluate(self, signal_context: dict) -> tuple[bool, float, list[dict]]:
        """
        Evaluate a signal against all rules.
        Returns (should_trade, score, matched_rules).
        """
        if not self.rules:
            return True, 1.0, []

        total_score = 0.0
        matched = []

        for rule in self.rules:
            condition = rule.get("condition", "")
            weight = rule.get("weight", 0)
            name = rule.get("name", "")

            match = self._check_condition(condition, signal_context)
            if match:
                total_score += weight
                matched.append({
                    "rule": name,
                    "weight": weight,
                    "matched": True,
                })

        passed = total_score >= self.threshold
        return passed, total_score, matched

    def _check_condition(self, condition: str, ctx: dict) -> bool:
        """Simple condition evaluator for rule conditions."""
        try:
            if "==" in condition:
                parts = condition.split("==")
                field = parts[0].strip()
                value = parts[1].strip().strip("'\"")
                return str(ctx.get(field, "")) == value

            if "between" in condition.lower():
                parts = condition.split()
                field = parts[0]
                low = float(parts[2])
                high = float(parts[4])
                val = ctx.get(field)
                if val is None:
                    return False
                return low <= float(val) <= high

            if ">" in condition:
                parts = condition.split(">")
                field = parts[0].strip()
                threshold = float(parts[1].strip())
                val = ctx.get(field)
                if val is None:
                    return False
                return float(val) > threshold

            if "<" in condition:
                parts = condition.split("<")
                field = parts[0].strip()
                threshold = float(parts[1].strip())
                val = ctx.get(field)
                if val is None:
                    return False
                return float(val) < threshold

            if "in" in condition:
                return False  # Complex conditions not evaluated here

        except (ValueError, IndexError, TypeError):
            pass

        return False


class TradeIntent:
    """Represents an intent to trade, pending risk approval."""

    def __init__(
        self,
        agent_id: str,
        symbol: str,
        side: str,
        signal_confidence: float,
        intelligence_score: float,
        matched_rules: list[dict],
        source_message: str = "",
        option_strike: Optional[float] = None,
        option_type: Optional[str] = None,
        option_expiry: Optional[str] = None,
    ):
        self.id = str(uuid.uuid4())
        self.agent_id = agent_id
        self.symbol = symbol
        self.side = side
        self.signal_confidence = signal_confidence
        self.intelligence_score = intelligence_score
        self.matched_rules = matched_rules
        self.source_message = source_message
        self.option_strike = option_strike
        self.option_type = option_type
        self.option_expiry = option_expiry
        self.created_at = datetime.now(timezone.utc)
        self.status = "PENDING"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "agent_id": self.agent_id,
            "symbol": self.symbol,
            "side": self.side,
            "signal_confidence": self.signal_confidence,
            "intelligence_score": self.intelligence_score,
            "matched_rules": self.matched_rules,
            "option_strike": self.option_strike,
            "option_type": self.option_type,
            "option_expiry": self.option_expiry,
            "created_at": self.created_at.isoformat(),
            "status": self.status,
        }


class LiveTradingPipeline:
    """
    End-to-end pipeline for processing live messages into trade executions.
    """

    def __init__(
        self,
        agent_id: str,
        agent_config: dict,
        intelligence_rules: list[dict],
        risk_chain=None,
        executor=None,
    ):
        self.agent_id = agent_id
        self.config = agent_config
        self.intelligence = IntelligenceFilter(intelligence_rules)
        self.risk_chain = risk_chain
        self.executor = executor

        self._signals_received = 0
        self._signals_passed = 0
        self._trades_executed = 0
        self._trades_rejected = 0

    async def process_message(self, content: str, author: str = "", channel: str = "") -> Optional[dict]:
        """
        Process a single incoming message through the full pipeline.
        Returns trade result dict if a trade was executed, None otherwise.
        """
        self._signals_received += 1

        # Step 1: Parse signal
        signal = parse_signal(content)
        if signal.signal_type not in ("buy_signal", "sell_signal"):
            return None

        if not signal.primary_ticker:
            return None

        # Step 2: Build context for intelligence filter
        now = datetime.now(timezone.utc)
        signal_context = {
            "ticker": signal.primary_ticker,
            "hour_of_day": now.hour,
            "day_of_week": now.weekday(),
            "author": author,
            "channel": channel,
            "signal_type": signal.signal_type,
            "is_pre_market": now.hour < 9 or (now.hour == 9 and now.minute < 30),
        }

        # Step 3: Apply intelligence filter
        passed, score, matched_rules = self.intelligence.evaluate(signal_context)

        if not passed:
            self._trades_rejected += 1
            logger.info(
                "Signal REJECTED by intelligence filter: %s %s (score=%.2f)",
                signal.signal_type, signal.primary_ticker, score,
            )
            return {
                "action": "rejected",
                "reason": "intelligence_filter",
                "score": score,
                "ticker": signal.primary_ticker,
            }

        self._signals_passed += 1

        # Step 4: Create trade intent
        intent = TradeIntent(
            agent_id=self.agent_id,
            symbol=signal.primary_ticker,
            side="buy" if signal.signal_type == "buy_signal" else "sell",
            signal_confidence=signal.confidence,
            intelligence_score=score,
            matched_rules=matched_rules,
            source_message=content[:200],
            option_strike=signal.option_strike,
            option_type=signal.option_type,
            option_expiry=signal.option_expiry,
        )

        # Step 5: Risk chain validation
        if self.risk_chain:
            risk_result = self.risk_chain.evaluate(intent.to_dict())
            if not risk_result.approved:
                intent.status = "RISK_REJECTED"
                self._trades_rejected += 1
                logger.info("Trade REJECTED by risk chain: %s", risk_result.reason)
                return {
                    "action": "risk_rejected",
                    "reason": risk_result.reason,
                    "intent": intent.to_dict(),
                }

        # Step 6: Execute
        if self.executor:
            try:
                fill = await self.executor.execute({
                    "symbol": intent.symbol,
                    "side": intent.side,
                    "qty": self._calculate_position_size(intent),
                    "order_type": "market",
                })
                intent.status = "EXECUTED"
                self._trades_executed += 1
                logger.info("Trade EXECUTED: %s %s", intent.side, intent.symbol)
                return {
                    "action": "executed",
                    "intent": intent.to_dict(),
                    "fill": fill,
                }
            except Exception as e:
                intent.status = "EXECUTION_FAILED"
                logger.error("Trade execution failed: %s", e)
                return {
                    "action": "execution_failed",
                    "error": str(e),
                    "intent": intent.to_dict(),
                }
        else:
            intent.status = "SIMULATED"
            self._trades_executed += 1
            return {
                "action": "simulated",
                "intent": intent.to_dict(),
            }

    def _calculate_position_size(self, intent: TradeIntent) -> int:
        """Calculate position size based on agent config."""
        max_position_pct = self.config.get("max_position_pct", 10)
        # Simplified: use a fixed qty for now
        return 100

    def get_stats(self) -> dict:
        return {
            "signals_received": self._signals_received,
            "signals_passed": self._signals_passed,
            "trades_executed": self._trades_executed,
            "trades_rejected": self._trades_rejected,
            "filter_pass_rate": (
                self._signals_passed / self._signals_received
                if self._signals_received > 0
                else 0
            ),
        }

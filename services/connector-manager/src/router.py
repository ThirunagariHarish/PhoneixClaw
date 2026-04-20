"""
Message router — routes normalized messages from connectors to target agents.

M1.9: Central routing logic for connector messages.
Reference: PRD Section 4 (Signal Flow), ArchitecturePlan §5.
"""
from __future__ import annotations

import logging
from typing import Any

from services.connector_manager.src.base import ConnectorMessage

logger = logging.getLogger(__name__)


class RouteRule(object):
    """A routing rule that maps connector + channel to agent(s)."""

    def __init__(
        self,
        connector_id: str,
        channel_pattern: str,
        target_agent_ids: list[str],
        transform: str | None = None,
    ):
        self.connector_id = connector_id
        self.channel_pattern = channel_pattern
        self.target_agent_ids = target_agent_ids
        self.transform = transform

    def matches(self, message: ConnectorMessage) -> bool:
        """Check if a message matches this route rule."""
        if message.source_id != self.connector_id:
            return False
        if self.channel_pattern == "*":
            return True
        return message.channel == self.channel_pattern


class MessageRouter:
    """
    Routes connector messages to subscribed agents based on configured rules.
    Supports wildcard matching and message transformation.
    """

    def __init__(self):
        self._rules: list[RouteRule] = []
        self._message_count = 0
        self._route_hits: dict[str, int] = {}

    def add_rule(self, rule: RouteRule) -> None:
        """Register a new routing rule."""
        self._rules.append(rule)

    def remove_rules_for_connector(self, connector_id: str) -> int:
        """Remove all rules for a given connector. Returns count removed."""
        before = len(self._rules)
        self._rules = [r for r in self._rules if r.connector_id != connector_id]
        return before - len(self._rules)

    def route(self, message: ConnectorMessage) -> list[str]:
        """
        Find all target agent IDs for a given message.
        Returns deduplicated list of agent IDs to receive this message.
        """
        self._message_count += 1
        targets: set[str] = set()
        for rule in self._rules:
            if rule.matches(message):
                for agent_id in rule.target_agent_ids:
                    targets.add(agent_id)
                    self._route_hits[agent_id] = self._route_hits.get(agent_id, 0) + 1

        if not targets:
            logger.debug("No route match for message from %s/%s", message.source_id, message.channel)

        return list(targets)

    def get_stats(self) -> dict[str, Any]:
        """Return routing statistics."""
        return {
            "total_messages_routed": self._message_count,
            "rule_count": len(self._rules),
            "route_hits_by_agent": dict(self._route_hits),
        }

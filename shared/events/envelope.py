"""Shared message envelope for Redis Stream events."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class EventType(str, Enum):
    TRADE_INTENT_CREATED = "trade.intent.created"
    TRADE_FILLED = "trade.filled"
    TRADE_REJECTED = "trade.rejected"
    POSITION_OPENED = "position.opened"
    POSITION_CLOSED = "position.closed"
    AGENT_STATUS_CHANGED = "agent.status.changed"
    AGENT_HEARTBEAT = "agent.heartbeat"
    CONNECTOR_STATUS = "connector.status"
    BACKTEST_STARTED = "backtest.started"
    BACKTEST_COMPLETED = "backtest.completed"
    SKILL_SYNCED = "skill.synced"
    AUTOMATION_TRIGGERED = "automation.triggered"
    DEV_INCIDENT = "dev.incident"
    AGENT_MESSAGE = "agent.message"
    KILL_SWITCH = "system.kill_switch"
    CIRCUIT_BREAKER = "system.circuit_breaker"


@dataclass
class Envelope:
    event_type: str
    data: dict[str, Any]
    source: str = "unknown"
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    version: str = "1.0"

    def to_redis(self) -> dict[str, str]:
        return {
            k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
            for k, v in asdict(self).items()
        }

    @classmethod
    def from_redis(cls, data: dict[bytes | str, bytes | str]) -> "Envelope":
        decoded = {}
        for k, v in data.items():
            key = k.decode() if isinstance(k, bytes) else k
            val = v.decode() if isinstance(v, bytes) else v
            if key == "data":
                val = json.loads(val)
            decoded[key] = val
        return cls(**decoded)

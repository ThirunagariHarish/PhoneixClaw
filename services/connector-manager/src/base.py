"""
Base connector abstract class — all connectors implement this interface.

M1.9: Connector Framework Core.
Reference: PRD Section 3.6 (Connectors Tab), ArchitecturePlan §3.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, AsyncIterator

from pydantic import BaseModel, Field


class ConnectorType(str, Enum):
    """Supported connector types."""
    DISCORD = "discord"
    REDDIT = "reddit"
    TWITTER = "twitter"
    UNUSUAL_WHALES = "unusual_whales"
    NEWS_API = "news_api"
    CUSTOM_WEBHOOK = "custom_webhook"
    TELEGRAM = "telegram"
    ANTHROPIC = "anthropic"


class ConnectorStatus(str, Enum):
    """Connector lifecycle states."""
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"


class ConnectorMessage(BaseModel):
    """
    Normalized message from any connector. All connectors produce this format
    regardless of their source, enabling uniform downstream processing.
    """
    source_type: ConnectorType
    source_id: str
    channel: str = ""
    author: str = ""
    content: str
    raw_data: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now())
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseConnector(ABC):
    """
    Abstract base class for all data source connectors.
    Implements the Template Method pattern for connection lifecycle.
    """

    def __init__(self, connector_id: str, config: dict[str, Any]):
        self.connector_id = connector_id
        self.config = config
        self.status = ConnectorStatus.DISCONNECTED
        self._error_count = 0
        self._last_message_at: datetime | None = None

    @property
    @abstractmethod
    def connector_type(self) -> ConnectorType:
        """Return the type of this connector."""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the data source."""
        ...

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Return health status of the connector."""
        ...

    @abstractmethod
    async def stream_messages(self) -> AsyncIterator[ConnectorMessage]:
        """Yield normalized messages as they arrive from the source."""
        ...

    async def test_connection(self) -> bool:
        """Test if the connector can reach its data source."""
        try:
            await self.connect()
            health = await self.health_check()
            await self.disconnect()
            return health.get("reachable", False)
        except Exception:
            return False

    def to_status_dict(self) -> dict[str, Any]:
        """Serialize connector status for API responses."""
        return {
            "connector_id": self.connector_id,
            "type": self.connector_type.value,
            "status": self.status.value,
            "error_count": self._error_count,
            "last_message_at": self._last_message_at.isoformat() if self._last_message_at else None,
        }

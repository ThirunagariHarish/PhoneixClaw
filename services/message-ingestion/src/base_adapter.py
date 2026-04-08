"""
Base adapter interface for pulling historical messages from various platforms.
Each platform adapter implements this interface to provide a uniform ingestion pipeline.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import AsyncIterator


@dataclass
class RawMessage:
    """Platform-agnostic message representation."""
    platform_message_id: str
    channel: str
    author: str
    content: str
    posted_at: datetime
    raw_data: dict = field(default_factory=dict)


class BaseMessageAdapter(ABC):
    """Abstract base for platform-specific message history adapters."""

    @abstractmethod
    async def pull_history(
        self,
        credentials: dict,
        config: dict,
        since: datetime,
        until: datetime,
        progress_callback=None,
    ) -> AsyncIterator[list[RawMessage]]:
        """
        Yield batches of historical messages from the platform.
        progress_callback(pulled_count, estimated_total) is called periodically.
        """
        ...

    @abstractmethod
    async def test_connection(self, credentials: dict, config: dict) -> tuple[bool, str]:
        """Quick connectivity check. Returns (success, detail_message)."""
        ...

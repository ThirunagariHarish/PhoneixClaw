"""
ChannelMessage model — stores ingested messages from Discord, Reddit, Twitter, etc.
Used by the backtesting pipeline to reconstruct trades from historical signals.
"""

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class ChannelMessage(Base):
    __tablename__ = "channel_messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id", ondelete="CASCADE"), nullable=False, index=True
    )
    channel: Mapped[str] = mapped_column(String(200), nullable=False)
    channel_id_snowflake: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    backfill_run_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unknown", index=True
    )  # buy_signal, sell_signal, close_signal, info, noise, unknown
    tickers_mentioned: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    platform_message_id: Mapped[str] = mapped_column(String(100), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

"""Feature Store models for caching computed ML features.

The feature_store_features table stores pre-computed features (technical
indicators, sentiment, market context) so that both training and inference
read from the same source — eliminating training/serving skew.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from shared.db.models.base import Base


class FeatureStoreFeature(Base):
    __tablename__ = "feature_store_features"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    feature_group: Mapped[str] = mapped_column(String(50), nullable=False)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        Index("ix_fs_ticker_group_time", "ticker", "feature_group", computed_at.desc()),
    )


class ModelBundle(Base):
    __tablename__ = "model_bundles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    minio_path: Mapped[str] = mapped_column(Text, nullable=False)
    primary_model: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    accuracy: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    auc_roc: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sharpe_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    training_trades: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feature_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    feature_schema: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    validation_passed: Mapped[Optional[bool]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    deployed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("uq_model_bundle_agent_version", "agent_id", "version", unique=True),
    )


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    agent_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_bundle_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    signal_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    features_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    prediction: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    reasoning: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow
    )
    actual_outcome: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    actual_pnl: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    outcome_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_pred_agent_time", "agent_id", predicted_at.desc()),
    )

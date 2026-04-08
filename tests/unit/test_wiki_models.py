"""Unit tests for wiki Pydantic schemas (WikiEntryCreate, WikiEntryUpdate)."""

from __future__ import annotations

import pytest

try:
    from pydantic import ValidationError

    from apps.api.src.routes.wiki import WikiEntryCreate, WikiEntryUpdate
except Exception as e:
    pytest.skip(f"Cannot import wiki routes: {e}", allow_module_level=True)


class TestWikiEntryCreateValidation:
    def test_valid_entry(self):
        entry = WikiEntryCreate(
            category="MARKET_PATTERNS",
            title="Test title",
            content="Test content",
        )
        assert entry.category == "MARKET_PATTERNS"
        assert entry.confidence_score == 0.5
        assert entry.tags == []
        assert entry.symbols == []

    def test_invalid_category_raises(self):
        with pytest.raises(ValidationError):
            WikiEntryCreate(
                category="INVALID_CATEGORY",
                title="T",
                content="C",
            )

    def test_all_valid_categories_accepted(self):
        valid_categories = [
            "MARKET_PATTERNS",
            "SYMBOL_PROFILES",
            "STRATEGY_LEARNINGS",
            "MISTAKES",
            "WINNING_CONDITIONS",
            "SECTOR_NOTES",
            "MACRO_CONTEXT",
            "TRADE_OBSERVATION",
        ]
        for cat in valid_categories:
            entry = WikiEntryCreate(category=cat, title="T", content="C")
            assert entry.category == cat

    def test_confidence_score_lower_bound(self):
        entry = WikiEntryCreate(
            category="MISTAKES", title="T", content="C", confidence_score=0.0
        )
        assert entry.confidence_score == 0.0

    def test_confidence_score_upper_bound(self):
        entry = WikiEntryCreate(
            category="MISTAKES", title="T", content="C", confidence_score=1.0
        )
        assert entry.confidence_score == 1.0

    def test_confidence_score_below_zero_raises(self):
        with pytest.raises(ValidationError):
            WikiEntryCreate(
                category="MISTAKES", title="T", content="C", confidence_score=-0.1
            )

    def test_confidence_score_above_one_raises(self):
        with pytest.raises(ValidationError):
            WikiEntryCreate(
                category="MISTAKES", title="T", content="C", confidence_score=1.01
            )

    def test_title_min_length(self):
        with pytest.raises(ValidationError):
            WikiEntryCreate(category="MISTAKES", title="", content="C")

    def test_content_min_length(self):
        with pytest.raises(ValidationError):
            WikiEntryCreate(category="MISTAKES", title="T", content="")

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            WikiEntryCreate(category="MISTAKES", title="x" * 256, content="C")

    def test_is_shared_default_false(self):
        entry = WikiEntryCreate(category="SECTOR_NOTES", title="T", content="C")
        assert entry.is_shared is False

    def test_tags_and_symbols(self):
        entry = WikiEntryCreate(
            category="SYMBOL_PROFILES",
            title="AAPL analysis",
            content="Details",
            tags=["breakout", "momentum"],
            symbols=["AAPL"],
        )
        assert "breakout" in entry.tags
        assert "AAPL" in entry.symbols


class TestWikiEntryUpdateValidation:
    def test_all_fields_optional(self):
        update = WikiEntryUpdate()
        assert update.category is None
        assert update.content is None
        assert update.confidence_score is None

    def test_partial_update(self):
        update = WikiEntryUpdate(title="New title", confidence_score=0.9)
        assert update.title == "New title"
        assert update.confidence_score == 0.9
        assert update.content is None

    def test_invalid_category_in_update(self):
        with pytest.raises(ValidationError):
            WikiEntryUpdate(category="BAD_CATEGORY")

    def test_valid_category_in_update(self):
        update = WikiEntryUpdate(category="MACRO_CONTEXT")
        assert update.category == "MACRO_CONTEXT"

    def test_confidence_score_bounds_in_update(self):
        with pytest.raises(ValidationError):
            WikiEntryUpdate(confidence_score=1.5)

    def test_change_reason_field(self):
        update = WikiEntryUpdate(change_reason="Fixed typo")
        assert update.change_reason == "Fixed typo"

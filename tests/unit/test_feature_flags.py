from shared.feature_flags import FeatureFlags


class TestFeatureFlags:
    def test_default_flags(self):
        ff = FeatureFlags()
        assert ff.is_enabled("trailing_stops") is True
        assert ff.is_enabled("ml_scoring") is False

    def test_set_flag(self):
        ff = FeatureFlags()
        ff.set_flag("ml_scoring", True)
        assert ff.is_enabled("ml_scoring") is True

    def test_user_override(self):
        ff = FeatureFlags()
        ff.set_flag("ml_scoring", False, user_overrides={"user-1": True})
        assert ff.is_enabled("ml_scoring") is False
        assert ff.is_enabled("ml_scoring", user_id="user-1") is True

    def test_unknown_flag_defaults_false(self):
        ff = FeatureFlags()
        assert ff.is_enabled("nonexistent_flag") is False

    def test_get_all(self):
        ff = FeatureFlags()
        all_flags = ff.get_all()
        assert "trailing_stops" in all_flags
        assert "audit_logging" in all_flags

from __future__ import annotations
import logging

logger = logging.getLogger(__name__)

class FeatureFlags:
    def __init__(self):
        self._flags: dict[str, dict] = {}
        self._defaults: dict[str, bool] = {
            "paper_trading_only": False,
            "manual_approval": False,
            "trailing_stops": True,
            "twitter_ingestor": False,
            "reddit_ingestor": False,
            "notifications_enabled": True,
            "ml_scoring": False,
            "audit_logging": True,
        }

    def is_enabled(self, flag_name: str, user_id: str | None = None) -> bool:
        if flag_name in self._flags:
            flag = self._flags[flag_name]
            if user_id and user_id in flag.get("user_overrides", {}):
                return flag["user_overrides"][user_id]
            return flag.get("enabled", self._defaults.get(flag_name, False))
        return self._defaults.get(flag_name, False)

    def set_flag(self, flag_name: str, enabled: bool, user_overrides: dict[str, bool] | None = None):
        self._flags[flag_name] = {"enabled": enabled, "user_overrides": user_overrides or {}}
        logger.info("Feature flag '%s' set to %s", flag_name, enabled)

    def get_all(self) -> dict[str, bool]:
        result = dict(self._defaults)
        for name, flag in self._flags.items():
            result[name] = flag.get("enabled", False)
        return result

feature_flags = FeatureFlags()

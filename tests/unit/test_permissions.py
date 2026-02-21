from shared.models.trade import (
    ADMIN_PERMISSIONS,
    DEFAULT_PERMISSIONS,
    ROLE_PRESETS,
)


class TestPermissions:
    def test_default_permissions_exist(self):
        assert "trade_execute" in DEFAULT_PERMISSIONS
        assert "trade_view" in DEFAULT_PERMISSIONS
        assert "admin_access" in DEFAULT_PERMISSIONS
        assert "kill_switch" in DEFAULT_PERMISSIONS

    def test_default_view_permissions_true(self):
        assert DEFAULT_PERMISSIONS["trade_view"] is True
        assert DEFAULT_PERMISSIONS["positions_view"] is True
        assert DEFAULT_PERMISSIONS["sources_view"] is True
        assert DEFAULT_PERMISSIONS["accounts_view"] is True

    def test_default_admin_permissions_false(self):
        assert DEFAULT_PERMISSIONS["admin_users"] is False
        assert DEFAULT_PERMISSIONS["admin_access"] is False
        assert DEFAULT_PERMISSIONS["kill_switch"] is False
        assert DEFAULT_PERMISSIONS["system_config"] is False

    def test_admin_permissions_all_true(self):
        for key, val in ADMIN_PERMISSIONS.items():
            assert val is True, f"{key} should be True in ADMIN_PERMISSIONS"

    def test_role_presets_exist(self):
        assert "viewer" in ROLE_PRESETS
        assert "trader" in ROLE_PRESETS
        assert "manager" in ROLE_PRESETS
        assert "admin" in ROLE_PRESETS

    def test_viewer_cannot_execute(self):
        assert ROLE_PRESETS["viewer"]["trade_execute"] is False
        assert ROLE_PRESETS["viewer"]["trade_approve"] is False

    def test_trader_can_execute(self):
        assert ROLE_PRESETS["trader"]["trade_execute"] is True
        assert ROLE_PRESETS["trader"]["trade_approve"] is True
        assert ROLE_PRESETS["trader"]["positions_close"] is True

    def test_manager_has_system_config(self):
        assert ROLE_PRESETS["manager"]["system_config"] is True
        assert ROLE_PRESETS["manager"]["admin_users"] is True

    def test_admin_all_true(self):
        for key in DEFAULT_PERMISSIONS:
            assert ROLE_PRESETS["admin"][key] is True

    def test_all_presets_cover_all_permissions(self):
        for role, perms in ROLE_PRESETS.items():
            for key in DEFAULT_PERMISSIONS:
                assert key in perms, f"Role '{role}' missing permission '{key}'"

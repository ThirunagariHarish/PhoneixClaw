
from services.notification_service.src.discord_bot import ADMIN_IDS, TradingBot


class TestDiscordBot:
    def test_bot_creation(self):
        bot = TradingBot(admin_ids=[123456])
        assert bot is not None

    def test_admin_ids_set(self):
        TradingBot(admin_ids=[111, 222])
        assert 111 in ADMIN_IDS
        assert 222 in ADMIN_IDS

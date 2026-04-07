"""Telegram bot integration — per-agent group creation and outbound messaging."""
from .sender import TelegramSender, get_sender

__all__ = ["TelegramSender", "get_sender"]

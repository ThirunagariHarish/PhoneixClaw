"""Phoenix WhatsApp integration — outbound sender + Claude SDK channel."""
from .sdk_channel import WhatsAppSDKChannel, get_channel

try:
    from .sender import send_whatsapp_message  # legacy sync helper
except Exception:
    send_whatsapp_message = None  # type: ignore

__all__ = ["WhatsAppSDKChannel", "get_channel", "send_whatsapp_message"]

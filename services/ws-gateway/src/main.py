"""
WebSocket gateway entrypoint — runs create_gateway().
"""
import asyncio

from .gateway import create_gateway

if __name__ == "__main__":
    asyncio.run(create_gateway(host="0.0.0.0", port=8031))

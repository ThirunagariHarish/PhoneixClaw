"""WebSocket manager for real-time trade, position, and notification updates.

Clients connect with their JWT token as a query parameter:
  ws://host/ws/trades?token=<jwt>
  ws://host/ws/positions?token=<jwt>
  ws://host/ws/notifications?token=<jwt>
"""

import asyncio
import json
import logging
from collections import defaultdict

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from jose import JWTError, jwt

from shared.config.base_config import config

logger = logging.getLogger(__name__)
router = APIRouter()

_connections: dict[str, dict[str, list[WebSocket]]] = defaultdict(lambda: defaultdict(list))


def _authenticate_ws(token: str) -> str | None:
    try:
        payload = jwt.decode(token, config.auth.secret_key, algorithms=[config.auth.algorithm])
        if payload.get("type") != "access":
            return None
        return payload.get("sub")
    except JWTError:
        return None


async def _ws_handler(websocket: WebSocket, channel: str, token: str):
    user_id = _authenticate_ws(token)
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()
    _connections[channel][user_id].append(websocket)
    logger.info("WS connected: %s/%s (total=%d)", channel, user_id[:8], len(_connections[channel][user_id]))

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _connections[channel][user_id].remove(websocket)
        if not _connections[channel][user_id]:
            del _connections[channel][user_id]


@router.websocket("/ws/trades")
async def ws_trades(websocket: WebSocket, token: str = Query(...)):
    await _ws_handler(websocket, "trades", token)


@router.websocket("/ws/positions")
async def ws_positions(websocket: WebSocket, token: str = Query(...)):
    await _ws_handler(websocket, "positions", token)


@router.websocket("/ws/notifications")
async def ws_notifications(websocket: WebSocket, token: str = Query(...)):
    await _ws_handler(websocket, "notifications", token)


async def broadcast(channel: str, user_id: str, data: dict) -> None:
    """Push an event to all WebSocket connections for a user on a channel."""
    websockets = _connections.get(channel, {}).get(user_id, [])
    if not websockets:
        return
    payload = json.dumps(data, default=str)
    dead = []
    for ws in websockets:
        try:
            await ws.send_text(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            websockets.remove(ws)
        except ValueError:
            pass


async def run_ws_consumer() -> None:
    """Background task that consumes execution-results and pushes to WebSockets."""
    try:
        from shared.kafka_utils.consumer import KafkaConsumerWrapper
        consumer = KafkaConsumerWrapper("execution-results", "api-ws-push-group")
        await consumer.start()

        async def _handle(msg: dict, headers: dict) -> None:
            user_id = msg.get("user_id", "")
            if not user_id:
                raw_uid = headers.get("user_id") or headers.get(b"user_id")
                user_id = raw_uid.decode("utf-8") if isinstance(raw_uid, bytes) else (raw_uid or "")
            if user_id:
                await broadcast("trades", user_id, msg)
                if msg.get("status") in ("ERROR", "REJECTED"):
                    await broadcast("notifications", user_id, {
                        "type": "trade_alert",
                        "title": f"{msg.get('status')}: {msg.get('action')} {msg.get('ticker')}",
                        "body": msg.get("error_message", ""),
                    })

        await consumer.consume(_handle)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("WebSocket consumer failed")

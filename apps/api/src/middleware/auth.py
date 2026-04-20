"""
JWT auth middleware: validate Bearer token and set request.state.user_id.
M1.3. Reference: ImplementationPlan.md M1.3.
"""
from __future__ import annotations

from typing import Callable

from fastapi import Request, Response
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from apps.api.src.config import auth_settings


def decode_jwt(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            auth_settings.jwt_secret_key,
            algorithms=[auth_settings.jwt_algorithm],
        )
    except JWTError:
        return None


class JWTAuthMiddleware(BaseHTTPMiddleware):
    """Extract Bearer token, decode JWT, set request.state.user_id and request.state.is_admin."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request.state.user_id = None
        request.state.is_admin = False
        request.state.role = "viewer"
        request.state.permissions = []
        auth = request.headers.get("Authorization")
        if auth and auth.startswith("Bearer "):
            token = auth[7:]
            payload = decode_jwt(token)
            if payload and payload.get("type") == "access":
                request.state.user_id = payload.get("sub")
                request.state.is_admin = payload.get("admin") is True
                request.state.role = payload.get("role", "trader")
                request.state.permissions = payload.get("permissions", [])
        return await call_next(request)

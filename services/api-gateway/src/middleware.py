import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config.base_config import config

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/auth/register", "/auth/login", "/auth/refresh", "/docs", "/openapi.json"}


class JWTMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[no-untyped-def]
        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(status_code=401, content={"detail": "Missing authorization header"})

        token = auth_header.split(" ", 1)[1]
        try:
            payload = jwt.decode(token, config.auth.secret_key, algorithms=[config.auth.algorithm])
            if payload.get("type") != "access":
                return JSONResponse(status_code=401, content={"detail": "Invalid token type"})
            request.state.user_id = payload["sub"]
        except JWTError:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

        return await call_next(request)

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from jose import JWTError, jwt
from starlette.middleware.base import BaseHTTPMiddleware

from shared.config.base_config import config

logger = logging.getLogger(__name__)

PUBLIC_PATHS = {"/health", "/auth/register", "/auth/login", "/auth/refresh", "/docs", "/openapi.json"}

_rate_limiter = None
_rate_limiter_initialized = False


async def _get_rate_limiter():
    global _rate_limiter, _rate_limiter_initialized
    if _rate_limiter_initialized:
        return _rate_limiter
    _rate_limiter_initialized = True
    try:
        from shared.rate_limiter import SlidingWindowRateLimiter
        _rate_limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60)
        await _rate_limiter.connect()
    except Exception:
        logger.warning("Rate limiter unavailable, proceeding without rate limiting")
        _rate_limiter = None
    return _rate_limiter


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
            request.state.is_admin = payload.get("admin", False)
        except JWTError:
            return JSONResponse(status_code=401, content={"detail": "Invalid or expired token"})

        rl = await _get_rate_limiter()
        if rl:
            client_key = f"user:{request.state.user_id}"
            if not await rl.is_allowed(client_key):
                return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})

        return await call_next(request)

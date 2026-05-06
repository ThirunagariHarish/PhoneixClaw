"""
Global exception handler middleware.

Catches unhandled exceptions (including SQLAlchemy errors) and returns
structured JSON error responses instead of raw 500 tracebacks.
"""

import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("phoenix.api.error_handler")


class ErrorHandlerMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            return _handle_exception(request, exc)


def _handle_exception(request: Request, exc: Exception) -> JSONResponse:
    """Map known exception families to appropriate HTTP status codes."""
    status_code = 500
    detail = "Internal server error"

    try:
        from sqlalchemy.exc import (
            IntegrityError,
            OperationalError,
            SQLAlchemyError,
        )

        if isinstance(exc, IntegrityError):
            status_code = 409
            detail = "Data integrity conflict"
        elif isinstance(exc, OperationalError):
            status_code = 503
            detail = "Database unavailable"
        elif isinstance(exc, SQLAlchemyError):
            status_code = 500
            detail = "Database error"
    except ImportError:
        pass

    logger.error(
        "Unhandled %s on %s %s: %s",
        type(exc).__name__,
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )

    return JSONResponse(
        status_code=status_code,
        content={
            "error": detail,
            "type": type(exc).__name__,
            "path": request.url.path,
        },
    )

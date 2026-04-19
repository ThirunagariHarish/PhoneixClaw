import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": getattr(record, "service", record.name),
            "message": record.getMessage(),
            "logger": record.name,
        }
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        if hasattr(record, "trade_id"):
            log_entry["trade_id"] = record.trade_id
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id
        return json.dumps(log_entry)

def setup_logging(service_name: str, level: str = "INFO"):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)
    logging.getLogger(service_name).info("Structured logging initialized for %s", service_name)


def get_correlation_id() -> Optional[str]:
    """Get correlation_id from environment or return None."""
    return os.getenv("CORRELATION_ID")


class CorrelationLogFilter(logging.Filter):
    """Inject correlation_id into every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "correlation_id"):
            record.correlation_id = get_correlation_id() or ""  # type: ignore
        return True


def configure_logging_with_correlation(logger: logging.Logger):
    """Add correlation ID filter to a logger."""
    logger.addFilter(CorrelationLogFilter())


def log_with_correlation(logger: logging.Logger, level: int, msg: str, correlation_id: Optional[str] = None, **kwargs):
    """Log a message with correlation_id in extra."""
    cid = correlation_id or get_correlation_id()
    extra = kwargs.pop("extra", {})
    if cid:
        extra["correlation_id"] = cid
    logger.log(level, msg, extra=extra, **kwargs)

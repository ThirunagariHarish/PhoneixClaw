"""Abstract base class for all external data clients.

Codifies the patterns from FredClient: singleton management, disk caching with
configurable TTL, NaN-safe extraction, sync HTTP with timeout, and rate limiting.

Every subclass must implement ``get_features(ticker, as_of_date)`` which returns
a dict of feature-name to float (or ``np.nan``) -- never raises.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class BaseDataClient(ABC):
    """Abstract base for all Phoenix external data clients.

    Provides:
    - Singleton via ``get_instance()`` class method
    - Disk-based JSON cache with configurable TTL
    - ``_safe_float`` / ``_safe_int`` NaN-safe extractors
    - ``_http_get`` sync HTTP method with timeout and error handling
    - Rate limiting (configurable requests per minute)
    - Abstract ``get_features`` contract for subclasses
    """

    _instance: "BaseDataClient | None" = None
    _instance_lock = threading.Lock()
    _class_locks: "dict[str, threading.Lock]" = {}
    _class_locks_guard = threading.Lock()

    def __init__(
        self,
        name: str,
        api_key_env: str = "",
        cache_dir: str | None = None,
        cache_ttl_hours: float = 12.0,
        base_url: str = "",
        requests_per_minute: int = 60,
    ):
        self._name = name
        self._api_key = os.getenv(api_key_env, "") if api_key_env else ""
        self._cache_dir = Path(
            cache_dir or os.getenv(
                f"{name.upper()}_CACHE_DIR",
                f"/tmp/phoenix_cache/{name}",
            )
        )
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_ttl_seconds = cache_ttl_hours * 3600
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._requests_per_minute = requests_per_minute
        self._request_timestamps: list[float] = []
        self._rate_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------
    @classmethod
    def get_instance(cls) -> "BaseDataClient":
        """Return the singleton instance, creating it if needed.

        Uses a per-class lock so that concurrent ``get_instance()`` calls on
        different subclasses do not serialize against each other.
        """
        cls_name = cls.__name__
        with BaseDataClient._class_locks_guard:
            if cls_name not in BaseDataClient._class_locks:
                BaseDataClient._class_locks[cls_name] = threading.Lock()
            lock = BaseDataClient._class_locks[cls_name]
        with lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ------------------------------------------------------------------
    # Disk cache
    # ------------------------------------------------------------------
    def _cache_key_path(self, key: str) -> Path:
        """Return a filesystem-safe cache path for *key*."""
        safe = hashlib.md5(key.encode(), usedforsecurity=False).hexdigest()
        return self._cache_dir / f"{safe}.json"

    def _is_cache_fresh(self, path: Path, ttl_seconds: float | None = None) -> bool:
        """Return True if *path* exists and is younger than *ttl_seconds*."""
        if not path.exists():
            return False
        ttl = ttl_seconds if ttl_seconds is not None else self._cache_ttl_seconds
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        return age < ttl

    def _read_cache(self, key: str, ttl_seconds: float | None = None) -> dict | None:
        """Read a cached JSON dict, or None if stale / missing."""
        path = self._cache_key_path(key)
        if not self._is_cache_fresh(path, ttl_seconds=ttl_seconds):
            return None
        try:
            return json.loads(path.read_text())
        except Exception:
            return None

    def _write_cache(self, key: str, data: dict) -> None:
        """Write *data* as JSON to disk cache."""
        path = self._cache_key_path(key)
        try:
            path.write_text(json.dumps(data, default=str))
        except Exception as exc:
            logger.debug("Cache write failed for %s: %s", key, exc)

    # ------------------------------------------------------------------
    # NaN-safe extractors
    # ------------------------------------------------------------------
    @staticmethod
    def _safe_float(val: Any, default: float = np.nan) -> float:
        """Convert *val* to float, returning *default* on any failure."""
        if val is None:
            return default
        try:
            result = float(val)
            if np.isnan(result) or np.isinf(result):
                return default
            return result
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_int(val: Any, default: int = 0) -> int:
        """Convert *val* to int, returning *default* on any failure."""
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    def _wait_for_rate_limit(self) -> None:
        """Block until we are within the requests-per-minute budget."""
        if self._requests_per_minute <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            window = 60.0
            self._request_timestamps = [
                t for t in self._request_timestamps if now - t < window
            ]
            if len(self._request_timestamps) >= self._requests_per_minute:
                sleep_for = window - (now - self._request_timestamps[0]) + 0.05
                if sleep_for > 0:
                    time.sleep(sleep_for)
            self._request_timestamps.append(time.monotonic())

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _http_get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        timeout: float = 15.0,
    ) -> dict:
        """Synchronous HTTP GET that returns parsed JSON dict.

        Raises ``RuntimeError`` on HTTP or network errors so the caller can
        fall back to cache or NaN.
        """
        import httpx

        self._wait_for_rate_limit()
        merged_headers = {"Accept": "application/json"}
        if headers:
            merged_headers.update(headers)
        try:
            resp = httpx.get(
                url,
                params=params,
                headers=merged_headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            raise RuntimeError(f"HTTP GET {url} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Abstract contract
    # ------------------------------------------------------------------
    @abstractmethod
    def get_features(self, ticker: str, as_of_date: date) -> dict[str, float]:
        """Return a dict of feature-name -> float for *ticker* as of *as_of_date*.

        Subclasses MUST:
        - Never raise -- catch all exceptions and return NaN values.
        - Return ``np.nan`` for any feature that cannot be computed.
        """
        ...

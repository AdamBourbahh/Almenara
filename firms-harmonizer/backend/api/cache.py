"""Deterministic, bounded, thread-safe in-memory LRU cache for analysis responses."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any

import numpy as np
import orjson

DEFAULT_MAXSIZE = 64


def make_cache_key(cells: list[int], params: dict, cube_mtime_ns: int) -> str:
    """BLAKE2b over sorted unique cells, key-sorted params and the cube modification time."""
    payload = (np.unique(np.asarray(cells, dtype=np.uint64)).astype("<u8").tobytes() + b"|"
               + orjson.dumps(params, option=orjson.OPT_SORT_KEYS) + b"|"
               + str(int(cube_mtime_ns)).encode())
    return hashlib.blake2b(payload, digest_size=32).hexdigest()


def _nbytes(value: Any) -> int:
    """Approximate retained size of a cached value (0 when it does not report one)."""
    return int(getattr(value, "nbytes", 0))


class LRUCache:
    """LRU bounded by entry count and, optionally, by the total ``nbytes`` of its values."""

    def __init__(self, maxsize: int = DEFAULT_MAXSIZE, max_bytes: int | None = None) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        if max_bytes is not None and max_bytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self.maxsize = maxsize
        self.max_bytes = max_bytes
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: str, value: Any) -> None:
        size = _nbytes(value)
        with self._lock:
            if self.max_bytes is not None and size > self.max_bytes:
                return  # larger than the whole budget: serve it, never cache it
            if key in self._data:
                self._bytes -= _nbytes(self._data[key])
            self._data[key] = value
            self._data.move_to_end(key)
            self._bytes += size
            while len(self._data) > self.maxsize or (self.max_bytes is not None and self._bytes > self.max_bytes):
                _, evicted = self._data.popitem(last=False)
                self._bytes -= _nbytes(evicted)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._bytes = 0

    @property
    def nbytes(self) -> int:
        with self._lock:
            return self._bytes

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


def geometry_key(coords: list) -> str:
    """BLAKE2b of the polygon coordinates, for the H3 filter cache."""
    return hashlib.blake2b(orjson.dumps(coords), digest_size=32).hexdigest()


class CachedJSON:
    """Serialized response split around the top-level execution_time_ms value, so a hit only splices."""

    __slots__ = ("head", "tail")
    FIELD = b'"execution_time_ms":'

    def __init__(self, body: bytes) -> None:
        start = body.index(self.FIELD) + len(self.FIELD)
        end = start
        while body[end:end + 1] not in (b",", b"}"):
            end += 1
        self.head, self.tail = body[:start], body[end:]

    def render(self, execution_time_ms: float) -> bytes:
        return self.head + orjson.dumps(float(execution_time_ms)) + self.tail

    @property
    def nbytes(self) -> int:
        return len(self.head) + len(self.tail)


class CachedGeometry(tuple):
    """(R4 parents, R7 cells, area km²) with a size estimate for the byte-bounded cache."""

    __slots__ = ()
    # A Python int in a list costs ~36 bytes (8-byte pointer + 28-byte int object).
    BYTES_PER_CELL = 36

    def __new__(cls, value: tuple[list[int], list[int], float]) -> "CachedGeometry":
        return super().__new__(cls, value)

    @property
    def nbytes(self) -> int:
        return (len(self[0]) + len(self[1])) * self.BYTES_PER_CELL


# A full 2001-2026 /analyze body for a ~1M km² AOI is ~16 MB; the budgets keep the worst case
# at a few hundred MB instead of 64 × that.
ANALYZE_CACHE_MAX_BYTES = 256 * 1024 * 1024
GEOMETRY_CACHE_MAX_BYTES = 128 * 1024 * 1024
ANALYZE_CACHE = LRUCache(DEFAULT_MAXSIZE, max_bytes=ANALYZE_CACHE_MAX_BYTES)
GEOMETRY_CACHE = LRUCache(DEFAULT_MAXSIZE, max_bytes=GEOMETRY_CACHE_MAX_BYTES)

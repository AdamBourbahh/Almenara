"""Deterministic, bounded, thread-safe in-memory LRU cache for analysis responses."""

from __future__ import annotations

import hashlib
import threading
import sys
from collections import OrderedDict
from typing import Any

import numpy as np
import orjson

DEFAULT_MAXSIZE = 64


def _size(value):
    if hasattr(value, "nbytes"):
        return int(value.nbytes)
    if isinstance(value, CachedJSON):
        return len(value.head) + len(value.tail)
    if isinstance(value, dict):
        return sys.getsizeof(value) + sum(_size(k) + _size(v) for k, v in value.items())
    if isinstance(value, (tuple, list)):
        return sys.getsizeof(value) + sum(map(_size, value))
    if hasattr(value, 'model_dump_json'):
        return len(value.model_dump_json().encode())
    return sys.getsizeof(value)


def make_cache_key(cells: list[int], params: dict, cube_mtime_ns: int) -> str:
    """BLAKE2b over sorted unique cells, key-sorted params and the cube modification time."""
    payload = (np.asarray(sorted(set(cells)), dtype="<u8").tobytes() + b"|"
               + orjson.dumps(params, option=orjson.OPT_SORT_KEYS) + b"|"
               + str(int(cube_mtime_ns)).encode())
    return hashlib.blake2b(payload, digest_size=32).hexdigest()


class LRUCache:
    def __init__(self, maxsize: int = DEFAULT_MAXSIZE, maxbytes: int = 128 * 1024 * 1024, *, max_bytes: int | None = None) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.maxsize = maxsize
        self.maxbytes = maxbytes if max_bytes is None else max_bytes
        if self.maxbytes < 1:
            raise ValueError("max_bytes must be >= 1")
        self._bytes = 0
        self._sizes: dict[str, int] = {}
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key: str, value: Any) -> None:
        with self._lock:
            size = _size(value)
            if key in self._data:
                self._bytes -= self._sizes.pop(key)
                del self._data[key]
            if size > self.maxbytes:
                return
            self._data[key] = value
            self._sizes[key] = size
            self._bytes += size
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize or self._bytes > self.maxbytes:
                old, _ = self._data.popitem(last=False)
                self._bytes -= self._sizes.pop(old)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
            self._sizes.clear()
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


ANALYZE_CACHE_MAX_BYTES = 128 * 1024 * 1024
GEOMETRY_CACHE_MAX_BYTES = 128 * 1024 * 1024
ANALYZE_CACHE = LRUCache(DEFAULT_MAXSIZE)
GEOMETRY_CACHE = LRUCache(DEFAULT_MAXSIZE)

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
    payload = (np.asarray(sorted(set(cells)), dtype="<u8").tobytes() + b"|"
               + orjson.dumps(params, option=orjson.OPT_SORT_KEYS) + b"|"
               + str(int(cube_mtime_ns)).encode())
    return hashlib.blake2b(payload, digest_size=32).hexdigest()


class LRUCache:
    def __init__(self, maxsize: int = DEFAULT_MAXSIZE) -> None:
        if maxsize < 1:
            raise ValueError("maxsize must be >= 1")
        self.maxsize = maxsize
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
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


ANALYZE_CACHE = LRUCache(DEFAULT_MAXSIZE)

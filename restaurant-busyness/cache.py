"""Tiny in-process TTL cache.

BestTime charges credits per API call, so every outbound response is
cached. Swap this for Redis if you run more than one worker process —
the interface is deliberately small.
"""

import threading
import time
from typing import Any, Callable, Optional


class TTLCache:
    def __init__(self, max_entries: int = 2000):
        self._data: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        now = time.time()
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value = entry
            if now >= expires_at:
                del self._data[key]
                self.misses += 1
                return None
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        with self._lock:
            if len(self._data) >= self._max_entries:
                self._evict_expired_locked()
                # Still full after cleanup: drop the soonest-to-expire entry.
                if len(self._data) >= self._max_entries:
                    oldest = min(self._data, key=lambda k: self._data[k][0])
                    del self._data[oldest]
            self._data[key] = (time.time() + ttl, value)

    def _evict_expired_locked(self) -> None:
        now = time.time()
        for key in [k for k, (exp, _) in self._data.items() if now >= exp]:
            del self._data[key]

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def stats(self) -> dict:
        with self._lock:
            return {"entries": len(self._data), "hits": self.hits, "misses": self.misses}


async def cached_call(
    cache: TTLCache,
    key: str,
    ttl: int,
    producer: Callable,
):
    """Return a cached value or await `producer()` and cache the result."""
    hit = cache.get(key)
    if hit is not None:
        return hit, True
    value = await producer()
    cache.set(key, value, ttl)
    return value, False

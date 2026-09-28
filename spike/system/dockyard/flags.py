"""Client-side cache over a read-only snapshot of feature_flags.

dockyard does not own the table; `read_rows` is whatever cross-service
fetch the caller wires up, and this module only decides when to re-fetch.
"""

from __future__ import annotations

import time
from collections.abc import Callable

CACHE_TTL_SECONDS = 60  # seconds before a cached snapshot is re-fetched


class FlagCache:
    """Wraps a `read_rows` callback and only re-invokes it once
    CACHE_TTL_SECONDS has elapsed since the last fetch."""

    def __init__(
        self,
        read_rows: Callable[[], dict[str, bool]],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._read_rows = read_rows
        self._clock = clock
        self._cached_at: float | None = None
        self._rows: dict[str, bool] = {}

    def rows(self) -> dict[str, bool]:
        """Return the cached snapshot, refreshing it first if it has aged
        past CACHE_TTL_SECONDS."""
        now = self._clock()
        if self._cached_at is None or now - self._cached_at >= CACHE_TTL_SECONDS:
            self._rows = self._read_rows()
            self._cached_at = now
        return self._rows


def is_enabled(cache: FlagCache, name: str) -> bool:
    """Look up `name` in the cached snapshot; a key that isn't present
    reads as False rather than raising."""
    return cache.rows().get(name, False)

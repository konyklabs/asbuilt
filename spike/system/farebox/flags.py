"""Registry of the flags this service knows about, plus a client-side
cache over the feature_flags table."""

from __future__ import annotations

import time
from collections.abc import Callable

FLAGS = {
    "dynamic_pricing": False,
    "ebike_surcharge": False,
    "overflow_parking": False,
    "refund_auto_approve": False,
}
# Registered flag names and their fallback value when no override exists.

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

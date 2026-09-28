"""Flag registry and cached reads.

F-065: the feature_flags table holds four flags: dynamic_pricing,
ebike_surcharge, overflow_parking and refund_auto_approve.
"""

from __future__ import annotations

import time
from collections.abc import Callable

FLAGS = {
    "dynamic_pricing": False,
    "ebike_surcharge": False,
    "overflow_parking": False,
    "refund_auto_approve": False,
}
"""F-049: dynamic_pricing is off by default. Every registered flag's
default is off."""

CACHE_TTL_SECONDS = 60
"""F-063: farebox and dockyard cache feature_flags rows for 60 seconds."""


class FlagCache:
    """Caches a snapshot of feature_flags rows for CACHE_TTL_SECONDS."""

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
        now = self._clock()
        if self._cached_at is None or now - self._cached_at >= CACHE_TTL_SECONDS:
            self._rows = self._read_rows()
            self._cached_at = now
        return self._rows


def is_enabled(cache: FlagCache, name: str) -> bool:
    """F-064: a flag with no row in feature_flags is treated as off."""
    return cache.rows().get(name, False)

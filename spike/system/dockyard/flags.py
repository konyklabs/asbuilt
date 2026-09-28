"""Reads feature_flags with a cache.

dockyard does not own feature_flags (farebox does); it reads a snapshot of
that table the same way farebox does, cached client-side.
"""

from __future__ import annotations

import time
from collections.abc import Callable

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

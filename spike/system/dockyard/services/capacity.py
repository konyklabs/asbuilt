"""Whether a station has room to accept one more bike."""

from __future__ import annotations

from dockyard.models.station import Station


def can_accept_bike(station: Station, docks_filled: int, overflow_parking_enabled: bool) -> bool:
    """True when `docks_filled` is under `station.capacity`, or when the
    caller has already been told the overflow switch is on."""
    if docks_filled < station.capacity:
        return True
    return overflow_parking_enabled

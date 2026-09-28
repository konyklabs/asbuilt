"""Station capacity rule.

F-017: a check-in at a full station is refused when the overflow_parking
flag is off.
F-018: when the overflow_parking flag is on, a bike can be checked in at a
full station.
"""

from __future__ import annotations

from dockyard.models.station import Station


def can_accept_bike(station: Station, docks_filled: int, overflow_parking_enabled: bool) -> bool:
    """Whether `station` can accept one more bike right now."""
    if docks_filled < station.capacity:
        return True
    return overflow_parking_enabled

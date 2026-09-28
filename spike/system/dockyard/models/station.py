"""Station model: a physical bike-share station with docks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Station:
    """A bike-share station: id, name, capacity, lat, lon."""

    id: str
    name: str
    capacity: int
    lat: float
    lon: float

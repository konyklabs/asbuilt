"""Dock model: a single bike slot at a station."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Dock:
    """A dock: station_id, bike_id (None if empty), state."""

    id: str
    station_id: str
    bike_id: str | None
    state: str

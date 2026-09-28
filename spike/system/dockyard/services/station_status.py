"""Station status read model.

F-052: GET /stations/{id}/status returns the station's available bikes,
empty docks and fill ratio.
"""

from __future__ import annotations

from dataclasses import dataclass

from dockyard.db import Session


class UnknownStationError(Exception):
    """Raised when the named station does not exist."""


@dataclass
class StationStatus:
    """A station's available bikes, empty docks and fill ratio."""

    station_id: str
    available_bikes: int
    empty_docks: int
    fill_ratio: float


def station_status(session: Session, station_id: str) -> StationStatus:
    """Compute a station's available bikes, empty docks and fill ratio."""
    station = session.stations.get(station_id)
    if station is None:
        raise UnknownStationError(station_id)
    docks = session.docks.for_station(station_id)
    filled = sum(1 for d in docks if d.bike_id is not None)
    empty = len(docks) - filled
    fill_ratio = filled / station.capacity if station.capacity else 0.0
    return StationStatus(
        station_id=station_id,
        available_bikes=filled,
        empty_docks=empty,
        fill_ratio=fill_ratio,
    )

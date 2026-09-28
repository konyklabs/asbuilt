"""Check-in."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from dockyard.clients.farebox import FareboxClient
from dockyard.db import Session
from dockyard.models.bike import BikeKind, BikeStatus
from dockyard.models.dock import Dock
from dockyard.services.capacity import can_accept_bike


class UnknownRideError(Exception):
    """Raised when check-in names a ride that does not exist."""


class UnknownStationError(Exception):
    """Raised when check-in names a station that does not exist."""


class StationFullError(Exception):
    """Raised when a station cannot accept a returning bike."""


def check_in(
    session: Session,
    farebox: FareboxClient,
    ride_id: str,
    station_id: str,
    now: datetime,
    overflow_parking_enabled: bool,
) -> dict[str, Any]:
    """Return a bike at `station_id`, closing its ride through farebox
    (F-055)."""
    ride = session.rides.get(ride_id)
    if ride is None:
        raise UnknownRideError(ride_id)
    station = session.stations.get(station_id)
    if station is None:
        raise UnknownStationError(station_id)

    docks_filled = sum(1 for d in session.docks.for_station(station_id) if d.bike_id is not None)
    if not can_accept_bike(station, docks_filled, overflow_parking_enabled):
        raise StationFullError(station_id)

    bike = session.bikes.get(ride.bike_id)
    dock = session.docks.empty_at(station_id)
    if dock is None:
        # Every normal-capacity dock is full: overflow parking (F-018).
        dock = Dock(id=str(uuid4()), station_id=station_id, bike_id=None, state="empty")
        session.docks.add(dock)
    dock.bike_id = bike.id
    dock.state = "occupied"

    bike.status = BikeStatus.AVAILABLE
    bike.station_id = station_id
    ride.return_station_id = station_id
    ride.ended_at = now
    ride.status = "closed"

    return farebox.close_ride(
        ride_id=ride.id,
        rider_id=ride.rider_id,
        bike_id=ride.bike_id,
        return_station_id=station_id,
        is_ebike=bike.kind == BikeKind.EBIKE,
        started_at=ride.started_at,
        ended_at=now,
    )

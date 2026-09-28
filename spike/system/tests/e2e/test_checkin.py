"""Check-in against station capacity."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dockyard.api.rides import checkin_endpoint
from dockyard.models.bike import Bike, BikeKind, BikeStatus
from dockyard.models.dock import Dock
from dockyard.models.ride import Ride
from dockyard.models.station import Station

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _full_station_with_open_ride(system, capacity: int = 1) -> Ride:
    dockyard = system.dockyard
    dockyard.session.stations.add(
        Station(id="station-full", name="Full Station", capacity=capacity, lat=0.0, lon=0.0)
    )
    for i in range(capacity):
        bike = Bike(
            id=f"parked-{i}",
            kind=BikeKind.CLASSIC,
            status=BikeStatus.AVAILABLE,
            station_id="station-full",
        )
        dockyard.session.bikes.add(bike)
        dockyard.session.docks.add(
            Dock(id=f"dock-{i}", station_id="station-full", bike_id=bike.id, state="occupied")
        )

    ride_bike = Bike(id="ride-bike", kind=BikeKind.CLASSIC, status=BikeStatus.IN_RIDE)
    dockyard.session.bikes.add(ride_bike)
    ride = Ride(
        id="ride-1",
        rider_id="rider-1",
        bike_id="ride-bike",
        start_station_id="station-origin",
        return_station_id=None,
        started_at=NOW - timedelta(minutes=20),
        ended_at=None,
        status="open",
    )
    dockyard.session.rides.add(ride)
    return ride


@pytest.mark.e2e
def test_checkin_at_full_station_refused(system):
    """One-capacity station, already occupied, flag off: checkin fails."""
    ride = _full_station_with_open_ride(system)
    status, body = checkin_endpoint(
        system.dockyard.session,
        system.dockyard.farebox,
        ride.id,
        "station-full",
        NOW,
        overflow_parking_enabled=False,
    )
    assert status == 409
    assert body["error"] == "station_full"


@pytest.mark.e2e
def test_checkin_full_station_returns_409(system):
    """Same setup; checks the exact response shape the client would see."""
    ride = _full_station_with_open_ride(system)
    status, body = checkin_endpoint(
        system.dockyard.session,
        system.dockyard.farebox,
        ride.id,
        "station-full",
        NOW,
        overflow_parking_enabled=False,
    )
    assert status == 409
    assert body == {"error": "station_full"}


@pytest.mark.e2e
def test_checkin_at_full_station_allowed_with_overflow_parking(system):
    """Same occupied station, flag switched on: checkin now succeeds."""
    ride = _full_station_with_open_ride(system)
    status, body = checkin_endpoint(
        system.dockyard.session,
        system.dockyard.farebox,
        ride.id,
        "station-full",
        NOW,
        overflow_parking_enabled=True,
    )
    assert status == 200
    assert body["ride_id"] == ride.id

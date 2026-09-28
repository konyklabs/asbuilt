"""Checkin-triggered ride closure, observed from the event side."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dockyard.api.rides import checkin_endpoint
from dockyard.models.bike import Bike, BikeKind, BikeStatus
from dockyard.models.dock import Dock
from dockyard.models.ride import Ride
from dockyard.models.station import Station

STARTED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
ENDED = STARTED + timedelta(minutes=10)


@pytest.mark.e2e
def test_close_ride_publishes_ride_completed(system):
    """Ten-minute ride, checked in normally: one event lands on the bus."""
    dockyard = system.dockyard
    dockyard.session.stations.add(Station(id="station-1", name="One", capacity=5, lat=0.0, lon=0.0))
    dockyard.session.docks.add(
        Dock(id="dock-1", station_id="station-1", bike_id=None, state="empty")
    )
    dockyard.session.bikes.add(Bike(id="bike-1", kind=BikeKind.CLASSIC, status=BikeStatus.IN_RIDE))
    ride = Ride(
        id="ride-1",
        rider_id="rider-1",
        bike_id="bike-1",
        start_station_id="station-0",
        return_station_id=None,
        started_at=STARTED,
        ended_at=None,
        status="open",
    )
    dockyard.session.rides.add(ride)

    status, _body = checkin_endpoint(
        dockyard.session,
        dockyard.farebox,
        ride.id,
        "station-1",
        ENDED,
        overflow_parking_enabled=False,
    )

    assert status == 200
    topic, payload = system.farebox.bus.published[0]
    assert topic == "ride.events"
    assert payload["type"] == "ride.completed"
    assert payload["ride_id"] == ride.id

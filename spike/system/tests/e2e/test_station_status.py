"""Station status read model."""

from __future__ import annotations

import pytest

from dockyard.api.stations import station_status_endpoint
from dockyard.models.bike import Bike, BikeKind, BikeStatus
from dockyard.models.dock import Dock
from dockyard.models.station import Station


@pytest.mark.e2e
def test_station_status_reports_fill_ratio(system):
    """F-052: GET /stations/{id}/status returns the station's available
    bikes, empty docks and fill ratio."""
    dockyard = system.dockyard
    dockyard.session.stations.add(Station(id="station-1", name="One", capacity=4, lat=0.0, lon=0.0))
    for i in range(4):
        dock = Dock(id=f"dock-{i}", station_id="station-1", bike_id=None, state="empty")
        dockyard.session.docks.add(dock)
        if i < 3:
            bike = Bike(
                id=f"bike-{i}",
                kind=BikeKind.CLASSIC,
                status=BikeStatus.AVAILABLE,
                station_id="station-1",
            )
            dockyard.session.bikes.add(bike)
            dock.bike_id = bike.id
            dock.state = "occupied"

    status, body = station_status_endpoint(dockyard.session, "station-1")

    assert status == 200
    assert body == {
        "station_id": "station-1",
        "available_bikes": 3,
        "empty_docks": 1,
        "fill_ratio": 0.75,
    }

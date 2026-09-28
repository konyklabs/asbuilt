"""Check-out limit."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from dockyard.api.rides import checkout_endpoint
from dockyard.models.bike import Bike, BikeKind, BikeStatus

NOW = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _add_bike(system, bike_id: str) -> None:
    system.dockyard.session.bikes.add(
        Bike(id=bike_id, kind=BikeKind.CLASSIC, status=BikeStatus.AVAILABLE)
    )


@pytest.mark.e2e
def test_third_checkout_refused(system):
    """Sequential checkouts for one rider, watching where the endpoint
    switches from success to the limit-reached error."""
    rider_id = "rider-1"
    for bike_id in ("bike-1", "bike-2", "bike-3"):
        _add_bike(system, bike_id)

    first = checkout_endpoint(system.dockyard.session, rider_id, "bike-1", "station-1", NOW)
    second = checkout_endpoint(system.dockyard.session, rider_id, "bike-2", "station-1", NOW)
    third = checkout_endpoint(system.dockyard.session, rider_id, "bike-3", "station-1", NOW)

    assert first[0] == 201
    assert second[0] == 201
    assert third == (409, {"error": "checkout_limit_reached"})

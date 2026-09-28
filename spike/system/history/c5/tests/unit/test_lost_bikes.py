"""Lost-bike closing and its fee."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from farebox.db import Store, build_session
from farebox.events import EventBus
from farebox.pricing import price_ride
from farebox.services.lost_bikes import LOST_BIKE_HOURS, OpenRide, close_lost_rides

STARTED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _open_ride(started_at: datetime) -> OpenRide:
    return OpenRide(
        ride_id="ride-1",
        rider_id="rider-1",
        bike_id="bike-1",
        return_station_id="station-1",
        is_member=False,
        is_ebike=False,
        started_at=started_at,
    )


@pytest.mark.unit
def test_ride_open_past_24_hours_closed_as_lost():
    """One ride, one minute past the staleness cutoff: gets swept up."""
    now = STARTED + timedelta(hours=LOST_BIKE_HOURS, minutes=1)
    session = build_session(Store())
    closed = close_lost_rides(session, EventBus(), now, [_open_ride(STARTED)])
    assert [c["ride_id"] for c in closed] == ["ride-1"]

    just_under = STARTED + timedelta(hours=LOST_BIKE_HOURS) - timedelta(minutes=1)
    still_open = close_lost_rides(
        build_session(Store()), EventBus(), just_under, [_open_ride(STARTED)]
    )
    assert still_open == []


@pytest.mark.unit
def test_lost_bike_fee_100():
    """The stale-ride surcharge, isolated from the underlying ride price."""
    now = STARTED + timedelta(hours=LOST_BIKE_HOURS, minutes=1)
    ride = _open_ride(STARTED)
    store = Store()
    session = build_session(store)

    closed = close_lost_rides(session, EventBus(), now, [ride])

    assert [c["ride_id"] for c in closed] == ["ride-1"]
    [line] = [line for line in store.invoice_lines.values() if line.ride_id == "ride-1"]
    assert line.amount_cents == closed[0]["amount_cents"]

    minutes = Decimal(str((now - STARTED).total_seconds() / 60))
    ride_charge_cents = price_ride(ride.is_member, minutes, ride.is_ebike, False)
    assert line.amount_cents - ride_charge_cents == 10000

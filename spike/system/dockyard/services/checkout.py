"""Check-out."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from dockyard.db import Session
from dockyard.models.bike import BikeStatus
from dockyard.models.ride import Ride
from dockyard.repositories.rides import open_rides_for_rider

CHECKOUT_LIMIT = 2  # open rides per rider


class UnknownBikeError(Exception):
    """Raised when check-out is attempted on a bike that does not exist."""


class BikeLockedError(Exception):
    """Raised when check-out is attempted on a locked bike."""


class CheckoutLimitReachedError(Exception):
    """Raised when the rider already holds CHECKOUT_LIMIT bikes."""


def check_out(
    session: Session, rider_id: str, bike_id: str, station_id: str, now: datetime
) -> Ride:
    """Open a new ride for `bike_id`.

    Raises BikeLockedError if the bike's status is locked, or
    CheckoutLimitReachedError once the rider already has CHECKOUT_LIMIT
    rides open.
    """
    bike = session.bikes.get(bike_id)
    if bike is None:
        raise UnknownBikeError(bike_id)
    if bike.status == BikeStatus.LOCKED:
        raise BikeLockedError(bike_id)
    if len(open_rides_for_rider(session.rides, rider_id)) >= CHECKOUT_LIMIT:
        raise CheckoutLimitReachedError(rider_id)

    dock = session.docks.occupied_by(bike_id)
    if dock is not None:
        dock.bike_id = None
        dock.state = "empty"

    ride = Ride(
        id=str(uuid4()),
        rider_id=rider_id,
        bike_id=bike_id,
        start_station_id=station_id,
        return_station_id=None,
        started_at=now,
        ended_at=None,
        status="open",
    )
    session.rides.add(ride)
    bike.status = BikeStatus.IN_RIDE
    bike.station_id = None
    return ride

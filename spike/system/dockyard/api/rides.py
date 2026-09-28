"""Handlers for the two ride-lifecycle endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from dockyard.api.errors import ERROR_CODES
from dockyard.clients.farebox import FareboxClient
from dockyard.db import Session
from dockyard.services.checkin import StationFullError, check_in
from dockyard.services.checkout import (
    BikeLockedError,
    CheckoutLimitReachedError,
    check_out,
)


def checkout_endpoint(
    session: Session, rider_id: str, bike_id: str, station_id: str, now: datetime
) -> tuple[int, dict[str, Any]]:
    """Handler for the check-out endpoint; maps each service exception to
    its own (status, body) pair rather than letting it propagate."""
    try:
        ride = check_out(session, rider_id, bike_id, station_id, now)
    except CheckoutLimitReachedError:
        return ERROR_CODES["checkout_limit_reached"], {"error": "checkout_limit_reached"}
    except BikeLockedError:
        return 409, {"error": "bike_locked"}
    return 201, {"ride_id": ride.id}


def checkin_endpoint(
    session: Session,
    farebox: FareboxClient,
    ride_id: str,
    station_id: str,
    now: datetime,
    overflow_parking_enabled: bool,
) -> tuple[int, dict[str, Any]]:
    """Handler wiring HTTP shape onto check_in: a capacity failure becomes
    an error body instead of propagating as an exception."""
    try:
        closed = check_in(session, farebox, ride_id, station_id, now, overflow_parking_enabled)
    except StationFullError:
        return ERROR_CODES["station_full"], {"error": "station_full"}
    return 200, closed

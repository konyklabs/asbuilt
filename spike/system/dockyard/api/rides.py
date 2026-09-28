"""POST /rides/checkout and POST /rides/{id}/checkin."""

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
    """POST /rides/checkout.

    F-070: returns HTTP 409 with error code checkout_limit_reached when the
    rider already holds 2 bikes.
    """
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
    """POST /rides/{id}/checkin.

    F-051: returns HTTP 409 with error code station_full at a full station.
    """
    try:
        closed = check_in(session, farebox, ride_id, station_id, now, overflow_parking_enabled)
    except StationFullError:
        return ERROR_CODES["station_full"], {"error": "station_full"}
    return 200, closed

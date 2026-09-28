"""Internal ride endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from farebox.clients.tollbooth import TollboothClient
from farebox.db import Session
from farebox.events import EventBus
from farebox.services.lost_bikes import OpenRide, close_lost_rides
from farebox.services.rides import close_ride


def close_ride_endpoint(
    session: Session,
    bus: EventBus,
    tollbooth: TollboothClient,
    ride_id: str,
    rider_id: str,
    bike_id: str,
    return_station_id: str,
    is_ebike: bool,
    started_at: datetime,
    ended_at: datetime,
    ebike_surcharge_enabled: bool,
    dynamic_pricing_enabled: bool,
    latest_severity: int | None,
) -> tuple[int, dict[str, Any]]:
    """POST /internal/rides/{id}/close.

    F-055: at check-in, dockyard calls this endpoint to price and close
    the ride.
    """
    result = close_ride(
        session,
        bus,
        tollbooth,
        ride_id,
        rider_id,
        bike_id,
        return_station_id,
        is_ebike,
        started_at,
        ended_at,
        ebike_surcharge_enabled,
        dynamic_pricing_enabled,
        latest_severity,
    )
    return 200, result


def close_lost_rides_endpoint(
    session: Session, bus: EventBus, now: datetime, open_rides: list[OpenRide]
) -> tuple[int, dict[str, Any]]:
    """POST /internal/rides/close-lost.

    F-069: the maintenance-sweep job calls this endpoint on every run.
    """
    closed = close_lost_rides(session, bus, now, open_rides)
    return 200, {"closed": closed}

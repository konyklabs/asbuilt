"""Closing lost rides."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

from farebox.db import Session
from farebox.events import EventBus, publish_ride_completed
from farebox.models.invoice import InvoiceLine
from farebox.pricing import LOST_BIKE_FEE, price_ride

LOST_BIKE_HOURS = 24
"""F-010: a ride whose bike is not docked within 24 hours of check-out is
closed as lost."""


@dataclass
class OpenRide:
    """The dockyard-owned ride facts farebox needs to close a lost ride,
    relayed to farebox by the maintenance-sweep job (F-069)."""

    ride_id: str
    rider_id: str
    bike_id: str
    return_station_id: str
    is_member: bool
    is_ebike: bool
    started_at: datetime


def close_lost_rides(
    session: Session, bus: EventBus, now: datetime, open_rides: list[OpenRide]
) -> list[dict[str, Any]]:
    """Close every ride in `open_rides` that has been open past
    LOST_BIKE_HOURS, charging the capped ride charge plus the lost-bike
    fee (F-026: the lost-bike fee is added on top of the capped ride
    charge), and publish ride.completed for each."""
    closed: list[dict[str, Any]] = []
    for ride in open_rides:
        if now - ride.started_at < timedelta(hours=LOST_BIKE_HOURS):
            continue
        minutes = Decimal(str((now - ride.started_at).total_seconds() / 60))
        ride_charge_cents = price_ride(ride.is_member, minutes, ride.is_ebike, False)
        amount_cents = ride_charge_cents + int(LOST_BIKE_FEE * 100)

        line = InvoiceLine(id=str(uuid4()), ride_id=ride.ride_id, amount_cents=amount_cents)
        session.invoices.add_line(line)
        publish_ride_completed(
            bus,
            ride.ride_id,
            ride.rider_id,
            ride.bike_id,
            ride.return_station_id,
            now,
            amount_cents,
        )
        closed.append({"ride_id": ride.ride_id, "amount_cents": amount_cents})
    return closed

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

LOST_BIKE_HOURS = 24  # hours since check-out before a ride is stale


@dataclass
class OpenRide:
    """The dockyard-owned ride facts farebox needs in order to evaluate
    and, if warranted, close out one ride relayed by dispatch."""

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
    """For each ride in `open_rides` still open past LOST_BIKE_HOURS,
    price it normally, add the flat LOST_BIKE_FEE on top, record the
    combined charge, and publish a completion event."""
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

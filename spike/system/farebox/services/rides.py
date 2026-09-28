"""Closing a ride: price, charge, publish."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

from farebox.clients.tollbooth import TollboothClient
from farebox.db import Session
from farebox.events import EventBus, publish_ride_completed
from farebox.models.invoice import InvoiceLine
from farebox.models.payment import Payment
from farebox.pricing import price_ride
from farebox.services.memberships import pricing_class
from farebox.services.surge import surge_multiplier


def close_ride(
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
) -> dict[str, Any]:
    """Price the ride, charge a casual rider through Tollbooth Pay
    (F-076: a casual ride is charged to the rider's card through Tollbooth
    Pay when the ride closes), and publish ride.completed (F-050)."""
    membership = session.memberships.for_rider(rider_id)
    is_member = pricing_class(membership) == "member"

    minutes = Decimal(str((ended_at - started_at).total_seconds() / 60))
    multiplier = surge_multiplier(dynamic_pricing_enabled, latest_severity)
    amount_cents = price_ride(is_member, minutes, is_ebike, ebike_surcharge_enabled, multiplier)

    line = InvoiceLine(id=str(uuid4()), ride_id=ride_id, amount_cents=amount_cents)
    session.invoices.add_line(line)

    if not is_member:
        payment = Payment(
            id=str(uuid4()), ride_id=ride_id, amount_cents=amount_cents, status="pending"
        )
        tollbooth.capture(ride_id, amount_cents)
        payment.status = "captured"
        session.payments.add(payment)

    publish_ride_completed(
        bus, ride_id, rider_id, bike_id, return_station_id, ended_at, amount_cents
    )
    return {"ride_id": ride_id, "amount_cents": amount_cents}

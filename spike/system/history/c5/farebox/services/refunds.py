"""Refund rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from farebox.db import Session
from farebox.events import EventBus, publish_ride_refunded
from farebox.models.refund import Refund, RefundStatus

REFUND_WINDOW_DAYS = 14
"""F-013: a refund requested more than 14 days after the ride ended is
rejected."""


class RefundWindowExpiredError(Exception):
    """Raised when a refund is requested more than REFUND_WINDOW_DAYS after
    the ride ended."""


class RefundExceedsChargeError(Exception):
    """Raised when a refund would exceed the ride's charge."""


def request_refund(
    session: Session,
    ride_id: str,
    ride_ended_at: datetime,
    charged_cents: int,
    requested_cents: int,
    now: datetime,
    **_ignored: object,
) -> Refund:
    """Create a refund request.

    F-013: rejects a request made more than REFUND_WINDOW_DAYS after the
    ride ended.
    F-028: rejects a request for more than was charged for the ride.
    F-027: every refund request is created in status requested and waits
    for a fares agent to review it.
    """
    if now - ride_ended_at > timedelta(days=REFUND_WINDOW_DAYS):
        raise RefundWindowExpiredError(ride_id)
    if requested_cents > charged_cents:
        raise RefundExceedsChargeError(ride_id)

    refund = Refund(
        id=str(uuid4()),
        ride_id=ride_id,
        amount_cents=requested_cents,
        status=RefundStatus.REQUESTED,
    )
    session.refunds.add(refund)
    return refund


def pay_refund(session: Session, bus: EventBus, refund: Refund) -> Refund:
    """F-056: farebox publishes a ride.refunded event to the ride.events
    queue when a refund is paid."""
    refund.status = RefundStatus.PAID
    publish_ride_refunded(bus, refund)
    return refund

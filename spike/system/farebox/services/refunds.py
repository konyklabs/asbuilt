"""Refund rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from farebox.db import Session
from farebox.events import EventBus, publish_ride_refunded
from farebox.models.refund import Refund, RefundStatus

REFUND_WINDOW_DAYS = 14
"""F-013: a refund requested more than 14 days after the ride ended is
rejected."""

AUTO_APPROVE_LIMIT = Decimal("5.00")
"""F-014: when the refund_auto_approve flag is on, a refund under $5.00 is
approved without review."""


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
    auto_approve_enabled: bool = False,
) -> Refund:
    """Create a refund request.

    F-013: rejects a request made more than REFUND_WINDOW_DAYS after the
    ride ended.
    F-028: rejects a request for more than was charged for the ride.
    F-014: when auto_approve_enabled and the amount is under
    AUTO_APPROVE_LIMIT, the refund is approved without a fares agent's
    review; otherwise it is created in status requested and waits for one.
    """
    if now - ride_ended_at > timedelta(days=REFUND_WINDOW_DAYS):
        raise RefundWindowExpiredError(ride_id)
    if requested_cents > charged_cents:
        raise RefundExceedsChargeError(ride_id)

    status = RefundStatus.REQUESTED
    if auto_approve_enabled and requested_cents < int(AUTO_APPROVE_LIMIT * 100):
        status = RefundStatus.APPROVED

    refund = Refund(id=str(uuid4()), ride_id=ride_id, amount_cents=requested_cents, status=status)
    session.refunds.add(refund)
    return refund


def pay_refund(session: Session, bus: EventBus, refund: Refund) -> Refund:
    """F-056: farebox publishes a ride.refunded event to the ride.events
    queue when a refund is paid."""
    refund.status = RefundStatus.PAID
    publish_ride_refunded(bus, refund)
    return refund

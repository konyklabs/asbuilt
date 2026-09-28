"""Refund rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from farebox.db import Session
from farebox.events import EventBus, publish_ride_refunded
from farebox.models.refund import Refund, RefundStatus

REFUND_WINDOW_DAYS = 14  # days, request cutoff


class RefundWindowExpiredError(Exception):
    """Raised when a request arrives after REFUND_WINDOW_DAYS has passed."""


class RefundExceedsChargeError(Exception):
    """Guards against a refund larger than what the rider actually paid."""


def request_refund(
    session: Session,
    ride_id: str,
    ride_ended_at: datetime,
    charged_cents: int,
    requested_cents: int,
    now: datetime,
    **_ignored: object,
) -> Refund:
    """Validate and record a refund request, always pending manual
    review; the auto-approval path does not exist yet at this point in
    the service's history.

    Raises if the window has passed or the amount exceeds what was
    charged.
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
    """Flip a refund to paid and emit the corresponding event."""
    refund.status = RefundStatus.PAID
    publish_ride_refunded(bus, refund)
    return refund

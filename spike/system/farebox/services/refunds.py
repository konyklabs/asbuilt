"""Refund rules."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4

from farebox.db import Session
from farebox.events import EventBus, publish_ride_refunded
from farebox.models.refund import Refund, RefundStatus

REFUND_WINDOW_DAYS = 14  # days, request cutoff

AUTO_APPROVE_LIMIT = Decimal("5.00")  # dollars, strict upper bound


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
    auto_approve_enabled: bool = False,
) -> Refund:
    """Validate and record a refund request.

    Raises if the window has passed or the amount exceeds what was
    charged. Otherwise stores the request; when `auto_approve_enabled`
    and the amount is under AUTO_APPROVE_LIMIT it starts pre-approved,
    else it starts pending manual review.
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
    """Flip a refund to paid and emit the corresponding event."""
    refund.status = RefundStatus.PAID
    publish_ride_refunded(bus, refund)
    return refund

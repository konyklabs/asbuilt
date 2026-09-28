"""Refund model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RefundStatus(StrEnum):
    """Where a refund sits in its review-and-payout lifecycle."""

    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


@dataclass
class Refund:
    """One rider's request to give back part or all of a ride's charge."""

    id: str
    ride_id: str
    amount_cents: int
    status: RefundStatus

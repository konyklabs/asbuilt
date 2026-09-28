"""Refund model."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RefundStatus(StrEnum):
    """A refund's status: requested, approved, rejected or paid."""

    REQUESTED = "requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    PAID = "paid"


@dataclass
class Refund:
    """A refund: amount_cents."""

    id: str
    ride_id: str
    amount_cents: int
    status: RefundStatus

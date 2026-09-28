"""Payment model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Payment:
    """One capture attempt against the payment provider."""

    id: str
    ride_id: str
    amount_cents: int
    status: str

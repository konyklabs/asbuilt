"""Payment model.

F-072: farebox stores money as integer cents in amount_cents columns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Payment:
    """A Tollbooth Pay capture: amount_cents, status."""

    id: str
    ride_id: str
    amount_cents: int
    status: str

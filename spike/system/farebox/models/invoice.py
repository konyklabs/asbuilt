"""Invoice and invoice line models."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Invoice:
    """Groups a rider's charges for one billing period."""

    id: str
    rider_id: str
    period_start: date
    period_end: date


@dataclass
class InvoiceLine:
    """A single charge row, linked back to the ride it came from."""

    id: str
    ride_id: str
    amount_cents: int
    invoice_id: str | None = None

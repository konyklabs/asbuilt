"""Invoice and invoice line models.

F-072: farebox stores money as integer cents in amount_cents columns.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Invoice:
    """A member's monthly invoice: one per calendar month."""

    id: str
    rider_id: str
    period_start: date
    period_end: date


@dataclass
class InvoiceLine:
    """One ride's charge on an invoice, stored as amount_cents."""

    id: str
    ride_id: str
    amount_cents: int
    invoice_id: str | None = None

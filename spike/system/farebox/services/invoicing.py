"""Monthly member invoices."""

from __future__ import annotations

from datetime import date
from uuid import uuid4

from farebox.db import Session
from farebox.models.invoice import Invoice, InvoiceLine


def build_monthly_invoice(
    session: Session, rider_id: str, period_start: date, period_end: date, lines: list[InvoiceLine]
) -> Invoice:
    """F-035: a member receives one invoice per calendar month with one
    invoice line per ride."""
    invoice = Invoice(
        id=str(uuid4()), rider_id=rider_id, period_start=period_start, period_end=period_end
    )
    session.invoices.add(invoice)
    for line in lines:
        line.invoice_id = invoice.id
        session.invoices.add_line(line)
    return invoice

"""Invoice queries."""

from __future__ import annotations

from farebox.models.invoice import Invoice, InvoiceLine


class InvoiceRepository:
    """CRUD over in-memory tables of Invoice and InvoiceLine rows."""

    def __init__(
        self,
        invoices: dict[str, Invoice] | None = None,
        lines: dict[str, InvoiceLine] | None = None,
    ) -> None:
        self._invoices: dict[str, Invoice] = invoices if invoices is not None else {}
        self._lines: dict[str, InvoiceLine] = lines if lines is not None else {}

    def add(self, invoice: Invoice) -> None:
        self._invoices[invoice.id] = invoice

    def get(self, invoice_id: str) -> Invoice | None:
        return self._invoices.get(invoice_id)

    def add_line(self, line: InvoiceLine) -> None:
        self._lines[line.id] = line

    def lines_for_invoice(self, invoice_id: str) -> list[InvoiceLine]:
        return [line for line in self._lines.values() if line.invoice_id == invoice_id]

    def lines_for_rider(self, rider_id: str, rider_of_ride: dict[str, str]) -> list[InvoiceLine]:
        """Every invoice line for rides belonging to `rider_id`, given a
        ride_id -> rider_id lookup supplied by the caller."""
        return [
            line for line in self._lines.values() if rider_of_ride.get(line.ride_id) == rider_id
        ]

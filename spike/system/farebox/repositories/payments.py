"""Payment queries."""

from __future__ import annotations

from farebox.models.payment import Payment


class PaymentRepository:
    """CRUD over an in-memory table of Payment rows."""

    def __init__(self, rows: dict[str, Payment] | None = None) -> None:
        self._rows: dict[str, Payment] = rows if rows is not None else {}

    def add(self, payment: Payment) -> None:
        self._rows[payment.id] = payment

    def get(self, payment_id: str) -> Payment | None:
        return self._rows.get(payment_id)

    def for_ride(self, ride_id: str) -> Payment | None:
        for payment in self._rows.values():
            if payment.ride_id == ride_id:
                return payment
        return None

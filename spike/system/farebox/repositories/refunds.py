"""Refund queries."""

from __future__ import annotations

from farebox.models.refund import Refund


class RefundRepository:
    """CRUD over an in-memory table of Refund rows."""

    def __init__(self, rows: dict[str, Refund] | None = None) -> None:
        self._rows: dict[str, Refund] = rows if rows is not None else {}

    def add(self, refund: Refund) -> None:
        self._rows[refund.id] = refund

    def get(self, refund_id: str) -> Refund | None:
        return self._rows.get(refund_id)

    def for_ride(self, ride_id: str) -> list[Refund]:
        return [r for r in self._rows.values() if r.ride_id == ride_id]

"""Rider queries."""

from __future__ import annotations

from farebox.models.rider import Rider


class RiderRepository:
    """CRUD over an in-memory table of Rider rows."""

    def __init__(self, rows: dict[str, Rider] | None = None) -> None:
        self._rows: dict[str, Rider] = rows if rows is not None else {}

    def add(self, rider: Rider) -> None:
        self._rows[rider.id] = rider

    def get(self, rider_id: str) -> Rider | None:
        return self._rows.get(rider_id)

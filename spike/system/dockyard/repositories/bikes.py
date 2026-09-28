"""Bike queries."""

from __future__ import annotations

from dockyard.models.bike import Bike


class BikeRepository:
    """CRUD over an in-memory table of Bike rows."""

    def __init__(self, rows: dict[str, Bike] | None = None) -> None:
        self._rows: dict[str, Bike] = rows if rows is not None else {}

    def add(self, bike: Bike) -> None:
        self._rows[bike.id] = bike

    def get(self, bike_id: str) -> Bike | None:
        return self._rows.get(bike_id)

    def all(self) -> list[Bike]:
        return list(self._rows.values())

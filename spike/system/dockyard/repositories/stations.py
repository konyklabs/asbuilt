"""Station queries."""

from __future__ import annotations

from dockyard.models.station import Station


class StationRepository:
    """CRUD over an in-memory table of Station rows."""

    def __init__(self, rows: dict[str, Station] | None = None) -> None:
        self._rows: dict[str, Station] = rows if rows is not None else {}

    def add(self, station: Station) -> None:
        self._rows[station.id] = station

    def get(self, station_id: str) -> Station | None:
        return self._rows.get(station_id)

    def all(self) -> list[Station]:
        return list(self._rows.values())

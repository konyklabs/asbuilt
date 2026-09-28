"""Dock queries."""

from __future__ import annotations

from dockyard.models.dock import Dock


class DockRepository:
    """CRUD and lookups over an in-memory table of Dock rows."""

    def __init__(self, rows: dict[str, Dock] | None = None) -> None:
        self._rows: dict[str, Dock] = rows if rows is not None else {}

    def add(self, dock: Dock) -> None:
        self._rows[dock.id] = dock

    def get(self, dock_id: str) -> Dock | None:
        return self._rows.get(dock_id)

    def for_station(self, station_id: str) -> list[Dock]:
        return [d for d in self._rows.values() if d.station_id == station_id]

    def empty_at(self, station_id: str) -> Dock | None:
        """An unoccupied dock at `station_id`, if one exists."""
        for dock in self.for_station(station_id):
            if dock.bike_id is None:
                return dock
        return None

    def occupied_by(self, bike_id: str) -> Dock | None:
        """The dock currently holding `bike_id`, if any."""
        for dock in self._rows.values():
            if dock.bike_id == bike_id:
                return dock
        return None

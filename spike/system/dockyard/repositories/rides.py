"""Ride queries."""

from __future__ import annotations

from dockyard.models.ride import Ride


class RideRepository:
    """CRUD over an in-memory table of Ride rows."""

    def __init__(self, rows: dict[str, Ride] | None = None) -> None:
        self._rows: dict[str, Ride] = rows if rows is not None else {}

    def add(self, ride: Ride) -> None:
        self._rows[ride.id] = ride

    def get(self, ride_id: str) -> Ride | None:
        return self._rows.get(ride_id)

    def for_rider(self, rider_id: str) -> list[Ride]:
        return [r for r in self._rows.values() if r.rider_id == rider_id]

    def all(self) -> list[Ride]:
        return list(self._rows.values())


def open_rides_for_rider(rides: RideRepository, rider_id: str) -> list[Ride]:
    """Filter a rider's rides down to the ones with no checkin recorded yet."""
    return [r for r in rides.for_rider(rider_id) if r.status == "open"]

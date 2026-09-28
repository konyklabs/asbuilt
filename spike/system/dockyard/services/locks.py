"""Bike locking."""

from __future__ import annotations

from dockyard.db import Session
from dockyard.models.bike import BikeStatus


class UnknownBikeError(Exception):
    """Raised when the named bike does not exist."""


def lock_bike(session: Session, bike_id: str) -> None:
    """Lock a bike so it cannot be checked out.

    Called by dispatch's maintenance sweep when a bike crosses the fault
    threshold.
    """
    bike = session.bikes.get(bike_id)
    if bike is None:
        raise UnknownBikeError(bike_id)
    bike.status = BikeStatus.LOCKED

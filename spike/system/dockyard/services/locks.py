"""Bike locking."""

from __future__ import annotations

from dockyard.db import Session
from dockyard.models.bike import BikeStatus


class UnknownBikeError(Exception):
    """Raised when the named bike does not exist."""


def lock_bike(session: Session, bike_id: str) -> None:
    """Set a bike's status field so check_out's availability lookup skips
    it going forward. Invoked by dispatch's maintenance job."""
    bike = session.bikes.get(bike_id)
    if bike is None:
        raise UnknownBikeError(bike_id)
    bike.status = BikeStatus.LOCKED

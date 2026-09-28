"""Bike model, its kind and status."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BikeKind(StrEnum):
    """A bike is either a classic pedal bike or an e-bike."""

    CLASSIC = "classic"
    EBIKE = "ebike"


class BikeStatus(StrEnum):
    """A bike's status: available, in a ride, locked, or lost."""

    AVAILABLE = "available"
    IN_RIDE = "in_ride"
    LOCKED = "locked"
    LOST = "lost"


@dataclass
class Bike:
    """A bike: id, kind, status, and the station it is docked at, if any."""

    id: str
    kind: BikeKind
    status: BikeStatus = BikeStatus.AVAILABLE
    station_id: str | None = None

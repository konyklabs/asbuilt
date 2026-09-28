"""Bike model, its kind and status."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BikeKind(StrEnum):
    """Pedal bike vs. electric-assist bike."""

    CLASSIC = "classic"
    EBIKE = "ebike"


class BikeStatus(StrEnum):
    """The lifecycle a bike row moves through between checkouts."""

    AVAILABLE = "available"
    IN_RIDE = "in_ride"
    LOCKED = "locked"
    LOST = "lost"


@dataclass
class Bike:
    """One fleet unit; `station_id` is None while it's out on a ride."""

    id: str
    kind: BikeKind
    status: BikeStatus = BikeStatus.AVAILABLE
    station_id: str | None = None

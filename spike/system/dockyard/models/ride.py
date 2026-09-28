"""Ride model on the rides table."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Ride:
    """One checkout-to-checkin span; `return_station_id` and `ended_at`
    stay unset while the ride is still open."""

    id: str
    rider_id: str
    bike_id: str
    start_station_id: str
    return_station_id: str | None
    started_at: datetime
    ended_at: datetime | None
    status: str

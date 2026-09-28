"""Ride model on the rides table.

F-054: the rides table stores the check-in station in the column
return_station_id.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass
class Ride:
    """A ride: rider_id, bike_id, start_station_id, return_station_id,
    started_at, ended_at, status."""

    id: str
    rider_id: str
    bike_id: str
    start_station_id: str
    return_station_id: str | None
    started_at: datetime
    ended_at: datetime | None
    status: str

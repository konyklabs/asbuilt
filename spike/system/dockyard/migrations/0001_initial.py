"""Creates stations, docks, bikes, rides."""

from __future__ import annotations


def upgrade() -> list[dict[str, object]]:
    """Declare dockyard's four tables and their columns."""
    return [
        {"table": "stations", "columns": ["id", "name", "capacity", "lat", "lon"]},
        {"table": "docks", "columns": ["id", "station_id", "bike_id", "state"]},
        {"table": "bikes", "columns": ["id", "kind", "status", "station_id"]},
        {
            "table": "rides",
            "columns": [
                "id",
                "rider_id",
                "bike_id",
                "start_station_id",
                "return_station_id",
                "started_at",
                "ended_at",
                "status",
            ],
        },
    ]

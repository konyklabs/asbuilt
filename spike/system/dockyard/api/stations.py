"""GET /stations/{id}/status."""

from __future__ import annotations

from typing import Any

from dockyard.db import Session
from dockyard.services.station_status import station_status


def station_status_endpoint(session: Session, station_id: str) -> tuple[int, dict[str, Any]]:
    """Handler for the station-status endpoint; shapes the read model into
    a JSON-friendly dict."""
    status = station_status(session, station_id)
    return 200, {
        "station_id": status.station_id,
        "available_bikes": status.available_bikes,
        "empty_docks": status.empty_docks,
        "fill_ratio": status.fill_ratio,
    }

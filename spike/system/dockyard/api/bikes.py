"""POST /bikes/{id}/lock."""

from __future__ import annotations

from typing import Any

from dockyard.db import Session
from dockyard.services.locks import lock_bike


def lock_bike_endpoint(session: Session, bike_id: str) -> tuple[int, dict[str, Any]]:
    """Handler for the bike-lock endpoint; delegates to lock_bike and
    shapes a JSON-friendly response."""
    lock_bike(session, bike_id)
    return 200, {"bike_id": bike_id, "status": "locked"}

"""HTTP client for farebox.

dockyard has no real HTTP stack in this fixture: `transport` stands in for
the wire call, a function from (method, path, json) to a (status, body)
tuple that a test can point at farebox's own endpoint functions in-process.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

FAREBOX_TIMEOUT_SECONDS = 2
"""Dockyard's client-side timeout for calls to farebox."""

Transport = Callable[[str, str, dict[str, Any]], tuple[int, dict[str, Any]]]


class FareboxCallError(Exception):
    """Raised when a call to farebox does not return HTTP 200."""


class FareboxClient:
    """Thin wrapper over the injected transport, one method per endpoint
    dockyard calls on farebox."""

    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def close_ride(
        self,
        ride_id: str,
        rider_id: str,
        bike_id: str,
        return_station_id: str,
        is_ebike: bool,
        started_at: datetime,
        ended_at: datetime,
    ) -> dict[str, Any]:
        """Ask farebox to price and close a ride; raises FareboxCallError
        unless the response status is 200."""
        status, body = self._transport(
            "POST",
            f"/internal/rides/{ride_id}/close",
            {
                "rider_id": rider_id,
                "bike_id": bike_id,
                "return_station_id": return_station_id,
                "is_ebike": is_ebike,
                "started_at": started_at.isoformat(),
                "ended_at": ended_at.isoformat(),
            },
        )
        if status != 200:
            raise FareboxCallError(f"close_ride({ride_id}) failed: {status} {body}")
        return body

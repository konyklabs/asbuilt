"""Error codes to HTTP statuses."""

from __future__ import annotations

ERROR_CODES = {
    "station_full": 409,
    "checkout_limit_reached": 409,
}
"""F-051: station_full returns 409. F-070: checkout_limit_reached returns
409."""

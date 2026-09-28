"""Error codes to HTTP statuses."""

from __future__ import annotations

ERROR_CODES = {
    "station_full": 409,
    "checkout_limit_reached": 409,
}
# HTTP status code an endpoint returns for each error code above.

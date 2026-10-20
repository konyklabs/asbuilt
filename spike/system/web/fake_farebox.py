"""A fake of farebox's rider-facing API, written from the team wiki, not from farebox.

The routes and error codes follow the Farebox API page; the fare numbers follow
the Fares overview page and the fares price sheet. It imports nothing from
farebox, so it answers the way those pages say farebox does.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

CASUAL_UNLOCK_FEE_CENTS = 100
CASUAL_RATE_CENTS = 25  # per minute
SINGLE_RIDE_CAP_CENTS = 2500
REFUND_WINDOW = timedelta(days=14)


class FakeFarebox:
    """In-memory stand-in for the two farebox routes the portal calls."""

    def __init__(self) -> None:
        self._refund_ids = count(1)

    def preview_fare(self, query: dict[str, str], _payload: dict[str, Any]):
        if query.get("member") == "1":
            return 501, {"error": "member_fares_not_faked"}
        minutes = int(query["minutes"])
        cents = CASUAL_UNLOCK_FEE_CENTS + minutes * CASUAL_RATE_CENTS
        return 200, {"amount_cents": min(cents, SINGLE_RIDE_CAP_CENTS)}

    def request_refund(self, _query: dict[str, str], payload: dict[str, Any]):
        ended = datetime.fromisoformat(payload["ride_ended_at"])
        if datetime.now(UTC) - ended > REFUND_WINDOW:
            return 422, {"error": "refund_window_expired"}
        if payload["requested_cents"] > payload["charged_cents"]:
            return 422, {"error": "refund_exceeds_charge"}
        return 201, {"refund_id": f"fake-refund-{next(self._refund_ids)}", "status": "requested"}

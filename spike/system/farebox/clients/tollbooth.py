"""HTTP client for Tollbooth Pay."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

MAX_RETRIES = 3
"""F-023: a failed Tollbooth Pay call is retried 3 times with backoff
before the payment is marked failed."""

BACKOFF_SECONDS = (0.5, 1, 2)
"""F-061: the Tollbooth Pay client waits 0.5, 1 and 2 seconds before its
three retries."""

Transport = Callable[[str, int], tuple[int | None, bool]]


class TollboothPaymentFailed(Exception):
    """Raised when a capture exhausts its retries without succeeding."""


def should_retry(status: int | None, timed_out: bool) -> bool:
    """F-062: the client retries only after a timeout or a 5xx response,
    never after a 4xx response."""
    if timed_out:
        return True
    if status is None:
        return False
    return 500 <= status < 600


class TollboothClient:
    """Calls Tollbooth Pay's capture endpoint, retrying on failure.

    `transport` stands in for the wire call: a function from
    (idempotency_key, amount_cents) to a (status, timed_out) pair, so
    tests can script a sequence of failures without any real network call.
    `sleep` is injectable so tests never actually wait through the
    backoff.
    """

    def __init__(
        self, transport: Transport, sleep: Callable[[float], None] = lambda seconds: None
    ) -> None:
        self._transport = transport
        self._sleep = sleep

    def capture(self, ride_id: str, amount_cents: int) -> dict[str, Any]:
        """F-059: every Tollbooth Pay capture sends the ride id as its
        idempotency key."""
        attempt = 0
        while True:
            status, timed_out = self._transport(ride_id, amount_cents)
            if not timed_out and status is not None and 200 <= status < 300:
                return {
                    "status": "captured",
                    "idempotency_key": ride_id,
                    "amount_cents": amount_cents,
                }
            if attempt >= MAX_RETRIES or not should_retry(status, timed_out):
                raise TollboothPaymentFailed(ride_id)
            self._sleep(BACKOFF_SECONDS[attempt])
            attempt += 1

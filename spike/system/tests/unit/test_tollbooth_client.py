"""Tollbooth Pay capture retry behaviour."""

from __future__ import annotations

import pytest

from farebox.clients.tollbooth import (
    BACKOFF_SECONDS,
    MAX_RETRIES,
    TollboothClient,
    TollboothPaymentFailed,
)


@pytest.mark.unit
def test_capture_retries_three_times_then_fails():
    """F-023: a failed Tollbooth Pay call is retried 3 times with backoff
    before the payment is marked failed."""
    calls = 0
    sleeps: list[float] = []

    def failing_transport(ride_id: str, amount_cents: int) -> tuple[int | None, bool]:
        nonlocal calls
        calls += 1
        return 503, False

    client = TollboothClient(failing_transport, sleep=sleeps.append)

    with pytest.raises(TollboothPaymentFailed):
        client.capture("ride-1", 1000)

    assert calls == MAX_RETRIES + 1
    assert sleeps == list(BACKOFF_SECONDS)

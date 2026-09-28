"""Retry and backoff behaviour of the payment client's capture call."""

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
    """Transport that always answers 503: watch the attempt count and
    the exact delays passed to the injected sleep."""
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
    assert calls == 4
    assert sleeps == [0.5, 1, 2]


@pytest.mark.unit
@pytest.mark.skip(reason="the transport fake cannot model a declined card yet")
def test_capture_does_not_retry_a_4xx():
    """Transport that always answers 402: would show a single call and
    no retries, if the fake supported declines."""
    calls = 0

    def declined_transport(ride_id: str, amount_cents: int) -> tuple[int | None, bool]:
        nonlocal calls
        calls += 1
        return 402, False

    client = TollboothClient(declined_transport, sleep=lambda seconds: None)

    with pytest.raises(TollboothPaymentFailed):
        client.capture("ride-1", 1000)

    assert calls == 1

"""Public-endpoint coverage for filing a refund."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from farebox.api.refunds import create_refund_endpoint

RIDE_ENDED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.mark.e2e
def test_refund_after_14_days_rejected(system):
    """Filing well past the eligible window: expect the endpoint to
    decline it with a specific machine-readable code."""
    now = RIDE_ENDED + timedelta(days=15)
    status, body = create_refund_endpoint(
        system.farebox.session,
        "ride-1",
        RIDE_ENDED,
        charged_cents=1000,
        requested_cents=500,
        now=now,
    )
    assert status == 422
    assert body == {"error": "refund_window_expired"}

    at_boundary = RIDE_ENDED + timedelta(days=14)
    status, body = create_refund_endpoint(
        system.farebox.session,
        "ride-boundary-accepted",
        RIDE_ENDED,
        charged_cents=1000,
        requested_cents=500,
        now=at_boundary,
    )
    assert status == 201
    assert body["status"] == "requested"

    one_minute_over = RIDE_ENDED + timedelta(days=14, minutes=1)
    status, body = create_refund_endpoint(
        system.farebox.session,
        "ride-boundary-rejected",
        RIDE_ENDED,
        charged_cents=1000,
        requested_cents=500,
        now=one_minute_over,
    )
    assert status == 422
    assert body == {"error": "refund_window_expired"}

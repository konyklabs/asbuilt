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


@pytest.mark.e2e
def test_refund_under_five_dollars_auto_approved_when_flag_on(system):
    """Small request, flag on, filed the next day: skips manual review."""
    now = RIDE_ENDED + timedelta(days=1)
    status, body = create_refund_endpoint(
        system.farebox.session,
        "ride-2",
        RIDE_ENDED,
        charged_cents=1000,
        requested_cents=499,
        now=now,
        auto_approve_enabled=True,
    )
    assert status == 201
    assert body["status"] == "approved"

    at_limit = RIDE_ENDED + timedelta(days=1)
    status, body = create_refund_endpoint(
        system.farebox.session,
        "ride-3",
        RIDE_ENDED,
        charged_cents=1000,
        requested_cents=500,
        now=at_limit,
        auto_approve_enabled=True,
    )
    assert status == 201
    assert body["status"] == "requested"

    status, body = create_refund_endpoint(
        system.farebox.session,
        "ride-4",
        RIDE_ENDED,
        charged_cents=1000,
        requested_cents=499,
        now=at_limit,
        auto_approve_enabled=False,
    )
    assert status == 201
    assert body["status"] == "requested"

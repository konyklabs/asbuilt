"""Refund request rules."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from farebox.api.refunds import create_refund_endpoint

RIDE_ENDED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.mark.e2e
def test_refund_after_14_days_rejected(system):
    """F-013: a refund requested more than 14 days after the ride ended is
    rejected."""
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


@pytest.mark.e2e
def test_refund_under_five_dollars_auto_approved_when_flag_on(system):
    """F-014: when the refund_auto_approve flag is on, a refund under
    $5.00 is approved without review."""
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

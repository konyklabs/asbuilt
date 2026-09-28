"""Ride charges, exercised end to end through the close-ride handler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from farebox.api.rides import close_ride_endpoint
from farebox.models.membership import Membership, MembershipStatus

STARTED = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


def _add_member(farebox_app, rider_id: str) -> None:
    farebox_app.session.memberships.add(
        Membership(
            id=f"membership-{rider_id}",
            rider_id=rider_id,
            plan_id="plan-monthly",
            status=MembershipStatus.ACTIVE,
            renews_at=STARTED + timedelta(days=30),
        )
    )


@pytest.mark.e2e
def test_casual_ride_charges_one_dollar_unlock_fee(system):
    """Zero-length trip with an unrecognised rider id: floor amount only."""
    farebox = system.farebox
    status, body = close_ride_endpoint(
        farebox.session,
        farebox.bus,
        farebox.tollbooth,
        "ride-casual",
        "rider-casual",
        "bike-1",
        "station-1",
        False,
        STARTED,
        STARTED,
        ebike_surcharge_enabled=False,
        dynamic_pricing_enabled=False,
        latest_severity=None,
    )
    assert status == 200
    assert body["amount_cents"] == 100


@pytest.mark.e2e
def test_member_first_thirty_minutes_free(system):
    """Seeded membership, a short trip, checking the returned total is
    zero rather than merely small."""
    farebox = system.farebox
    _add_member(farebox, "rider-member")
    ended = STARTED + timedelta(minutes=20)
    status, body = close_ride_endpoint(
        farebox.session,
        farebox.bus,
        farebox.tollbooth,
        "ride-member",
        "rider-member",
        "bike-2",
        "station-1",
        False,
        STARTED,
        ended,
        ebike_surcharge_enabled=False,
        dynamic_pricing_enabled=False,
        latest_severity=None,
    )
    assert status == 200
    assert body["amount_cents"] == 0

    exactly_free = STARTED + timedelta(minutes=30)
    status, body = close_ride_endpoint(
        farebox.session,
        farebox.bus,
        farebox.tollbooth,
        "ride-member-boundary-free",
        "rider-member",
        "bike-3",
        "station-1",
        False,
        STARTED,
        exactly_free,
        ebike_surcharge_enabled=False,
        dynamic_pricing_enabled=False,
        latest_severity=None,
    )
    assert status == 200
    assert body["amount_cents"] == 0

    one_over = STARTED + timedelta(minutes=31)
    status, body = close_ride_endpoint(
        farebox.session,
        farebox.bus,
        farebox.tollbooth,
        "ride-member-boundary-charged",
        "rider-member",
        "bike-4",
        "station-1",
        False,
        STARTED,
        one_over,
        ebike_surcharge_enabled=False,
        dynamic_pricing_enabled=False,
        latest_severity=None,
    )
    assert status == 200
    assert body["amount_cents"] == 15

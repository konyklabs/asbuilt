"""Membership transition after a renewal charge fails."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from farebox.models.membership import Membership, MembershipStatus
from farebox.services.memberships import GRACE_DAYS, handle_failed_renewal

FAILED_AT = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)


@pytest.mark.unit
def test_membership_lapses_7_days_after_failed_renewal():
    """Single failed-charge event on a healthy record; asserts the exact
    date math behind the new deadline field."""
    membership = Membership(
        id="membership-1",
        rider_id="rider-1",
        plan_id="plan-monthly",
        status=MembershipStatus.ACTIVE,
        renews_at=FAILED_AT,
    )
    handle_failed_renewal(membership, FAILED_AT)
    assert GRACE_DAYS == 7
    assert membership.status == MembershipStatus.GRACE
    assert membership.grace_ends_at == FAILED_AT + timedelta(days=GRACE_DAYS)

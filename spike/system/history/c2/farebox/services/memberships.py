"""Membership rules."""

from __future__ import annotations

from datetime import datetime, timedelta

from farebox.models.membership import Membership, MembershipStatus

GRACE_DAYS = 3
"""F-015: a membership lapses 3 days after a failed renewal."""


def handle_failed_renewal(membership: Membership, failed_at: datetime) -> Membership:
    """F-075: a failed renewal reported by the Tollbooth Pay webhook moves
    the membership to status grace and sets grace_ends_at."""
    membership.status = MembershipStatus.GRACE
    membership.grace_ends_at = failed_at + timedelta(days=GRACE_DAYS)
    return membership


def pricing_class(membership: Membership | None) -> str:
    """F-029: a rider whose membership is in grace is priced as a member,
    and a rider whose membership has lapsed is priced as a casual rider."""
    if membership is None:
        return "casual"
    if membership.status in (MembershipStatus.ACTIVE, MembershipStatus.GRACE):
        return "member"
    return "casual"

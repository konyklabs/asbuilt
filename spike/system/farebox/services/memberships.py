"""Membership rules."""

from __future__ import annotations

from datetime import datetime, timedelta

from farebox.models.membership import Membership, MembershipStatus

GRACE_DAYS = 7  # days a lapsed-payment membership stays in grace


def handle_failed_renewal(membership: Membership, failed_at: datetime) -> Membership:
    """Transition `membership` off active billing as of `failed_at`,
    stamping the cutoff by which the payment method needs fixing."""
    membership.status = MembershipStatus.GRACE
    membership.grace_ends_at = failed_at + timedelta(days=GRACE_DAYS)
    return membership


def pricing_class(membership: Membership | None) -> str:
    """Map a membership record to the pricing tier a ride should use:
    "member" while active or in grace, "casual" otherwise, including
    when there's no membership at all."""
    if membership is None:
        return "casual"
    if membership.status in (MembershipStatus.ACTIVE, MembershipStatus.GRACE):
        return "member"
    return "casual"

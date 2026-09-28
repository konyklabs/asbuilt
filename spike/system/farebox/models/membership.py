"""Membership model.

F-074: a membership has one of three statuses: active, grace or lapsed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MembershipStatus(StrEnum):
    """F-074: active, grace or lapsed."""

    ACTIVE = "active"
    GRACE = "grace"
    LAPSED = "lapsed"


@dataclass
class Membership:
    """A membership: status, renews_at, grace_ends_at."""

    id: str
    rider_id: str
    plan_id: str
    status: MembershipStatus
    renews_at: datetime
    grace_ends_at: datetime | None = None

"""Membership model."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class MembershipStatus(StrEnum):
    """Where a membership currently sits in its billing lifecycle."""

    ACTIVE = "active"
    GRACE = "grace"
    LAPSED = "lapsed"


@dataclass
class Membership:
    """Links a rider to a plan and tracks the current renewal state."""

    id: str
    rider_id: str
    plan_id: str
    status: MembershipStatus
    renews_at: datetime
    grace_ends_at: datetime | None = None

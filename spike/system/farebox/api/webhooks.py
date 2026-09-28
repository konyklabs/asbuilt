"""Tollbooth Pay webhook receiver."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from farebox.db import Session
from farebox.services.memberships import handle_failed_renewal


def tollbooth_webhook(
    session: Session, membership_id: str, failed_at: datetime
) -> tuple[int, dict[str, Any]]:
    """F-075: a failed renewal reported by the Tollbooth Pay webhook moves
    the membership to status grace and sets grace_ends_at."""
    membership = session.memberships.get(membership_id)
    if membership is None:
        return 404, {"error": "membership_not_found"}
    handle_failed_renewal(membership, failed_at)
    return 200, {
        "membership_id": membership.id,
        "status": membership.status.value,
        "grace_ends_at": membership.grace_ends_at.isoformat(),
    }

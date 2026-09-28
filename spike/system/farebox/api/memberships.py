"""Membership read endpoint."""

from __future__ import annotations

from typing import Any

from farebox.db import Session


def get_membership_endpoint(session: Session, membership_id: str) -> tuple[int, dict[str, Any]]:
    """GET a membership's current status."""
    membership = session.memberships.get(membership_id)
    if membership is None:
        return 404, {"error": "membership_not_found"}
    return 200, {
        "membership_id": membership.id,
        "status": membership.status.value,
        "grace_ends_at": membership.grace_ends_at.isoformat() if membership.grace_ends_at else None,
    }

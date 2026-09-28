"""Inbound callback endpoint for the payment provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from farebox.db import Session
from farebox.services.memberships import handle_failed_renewal


def tollbooth_webhook(
    session: Session, membership_id: str, failed_at: datetime
) -> tuple[int, dict[str, Any]]:
    """Handler for the payment provider's renewal-failure callback; looks
    the membership up by id and forwards it to handle_failed_renewal."""
    membership = session.memberships.get(membership_id)
    if membership is None:
        return 404, {"error": "membership_not_found"}
    handle_failed_renewal(membership, failed_at)
    return 200, {
        "membership_id": membership.id,
        "status": membership.status.value,
        "grace_ends_at": membership.grace_ends_at.isoformat(),
    }

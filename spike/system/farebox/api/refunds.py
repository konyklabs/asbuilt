"""POST /refunds."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from farebox.db import Session
from farebox.services.refunds import (
    RefundExceedsChargeError,
    RefundWindowExpiredError,
    request_refund,
)


def create_refund_endpoint(
    session: Session,
    ride_id: str,
    ride_ended_at: datetime,
    charged_cents: int,
    requested_cents: int,
    now: datetime,
    auto_approve_enabled: bool = False,
) -> tuple[int, dict[str, Any]]:
    """Handler for the refund-creation endpoint; maps request_refund's
    exceptions onto 422 responses with distinct error codes."""
    try:
        refund = request_refund(
            session,
            ride_id,
            ride_ended_at,
            charged_cents,
            requested_cents,
            now,
            auto_approve_enabled=auto_approve_enabled,
        )
    except RefundWindowExpiredError:
        return 422, {"error": "refund_window_expired"}
    except RefundExceedsChargeError:
        return 422, {"error": "refund_exceeds_charge"}
    return 201, {"refund_id": refund.id, "status": refund.status.value}

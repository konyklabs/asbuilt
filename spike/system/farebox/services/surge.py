"""Dynamic pricing multiplier."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

SURGE_MULTIPLIER = Decimal("1.25")
"""F-024: multiplies MEMBER_RATE and CASUAL_RATE only; not the unlock fee
or the e-bike surcharge."""

SURGE_MIN_SEVERITY = 2
"""F-024: the lowest Skyglass severity at which dynamic pricing surges
rates."""


def surge_multiplier(dynamic_pricing_enabled: bool, severity: int | None) -> Decimal:
    """F-024: when dynamic_pricing is on and the latest Skyglass severity
    is 2 or more, per-minute rates are multiplied by 1.25."""
    if dynamic_pricing_enabled and severity is not None and severity >= SURGE_MIN_SEVERITY:
        return SURGE_MULTIPLIER
    return Decimal("1")


def latest_severity(weather_readings: list[dict[str, Any]]) -> int | None:
    """F-066: farebox reads the weather_readings table, which dispatch
    owns, to compute the surge multiplier; returns the most recent row's
    severity, or None if there are no readings."""
    if not weather_readings:
        return None
    return max(weather_readings, key=lambda row: row["recorded_at"])["severity"]

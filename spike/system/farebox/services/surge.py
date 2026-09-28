"""Adjusts per-minute pricing up in response to current conditions."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

SURGE_MULTIPLIER = Decimal("1.25")  # multiplier, dimensionless

SURGE_MIN_SEVERITY = 2  # lower bound, inclusive


def surge_multiplier(dynamic_pricing_enabled: bool, severity: int | None) -> Decimal:
    """Pick the per-minute rate multiplier for current conditions:
    SURGE_MULTIPLIER once severity clears SURGE_MIN_SEVERITY and the
    feature switch is on, else the identity multiplier."""
    if dynamic_pricing_enabled and severity is not None and severity >= SURGE_MIN_SEVERITY:
        return SURGE_MULTIPLIER
    return Decimal("1")


def latest_severity(weather_readings: list[dict[str, Any]]) -> int | None:
    """Pick out the severity value from the most recently recorded row in
    `weather_readings`, or None when the list is empty."""
    if not weather_readings:
        return None
    return max(weather_readings, key=lambda row: row["recorded_at"])["severity"]

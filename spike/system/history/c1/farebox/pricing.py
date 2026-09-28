"""Ride pricing."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MEMBER_FREE_MINUTES = 30  # minutes, subtracted up front

MEMBER_RATE = Decimal("0.15")  # USD/min

CASUAL_RATE = Decimal("0.25")  # USD/min

CASUAL_UNLOCK_FEE = Decimal("1.00")  # USD, one-time

EBIKE_SURCHARGE = Decimal("0.10")  # USD/min, add-on rate

SINGLE_RIDE_CAP = Decimal("25.00")  # USD, upper clamp

LOST_BIKE_FEE = Decimal("100.00")  # USD, flat add-on


def price_ride(
    is_member: bool,
    minutes: Decimal,
    is_ebike: bool,
    ebike_surcharge_enabled: bool,
    surge_multiplier: Decimal = Decimal("1"),
) -> int:
    """Compute one ride's charge, in integer cents.

    Combines a flat unlock fee (casual riders only), the per-minute rate
    times charged minutes times the surge multiplier, and an optional
    e-bike surcharge on those same charged minutes, then clamps the sum
    to SINGLE_RIDE_CAP before rounding to the nearest cent.
    """
    if is_member:
        charged_minutes = max(minutes - MEMBER_FREE_MINUTES, Decimal(0))
        rate = MEMBER_RATE
        unlock_fee = Decimal("0")
    else:
        charged_minutes = minutes
        rate = CASUAL_RATE
        unlock_fee = CASUAL_UNLOCK_FEE

    charge = unlock_fee + charged_minutes * rate * surge_multiplier
    if is_ebike and ebike_surcharge_enabled:
        charge += charged_minutes * EBIKE_SURCHARGE

    charge = min(charge, SINGLE_RIDE_CAP)
    cents = (charge * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(cents)

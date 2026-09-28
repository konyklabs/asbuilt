"""Ride pricing."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

MEMBER_FREE_MINUTES = 30
"""F-001: a member's first 30 minutes of every ride are free."""

MEMBER_RATE = Decimal("0.15")
"""F-005: a member pays $0.15 per minute for every minute after the free
minutes."""

CASUAL_RATE = Decimal("0.25")
"""F-006: a rider without a membership pays $0.25 per minute from the
first minute of the ride."""

CASUAL_UNLOCK_FEE = Decimal("1.00")
"""F-004: a rider without a membership pays a $1.00 unlock fee for every
ride."""

EBIKE_SURCHARGE = Decimal("0.10")
"""F-007: when the ebike_surcharge flag is on, every charged minute of an
e-bike ride costs an extra $0.10. A member's free minutes are not charged,
so they carry no surcharge."""

SINGLE_RIDE_CAP = Decimal("25.00")
"""F-008: a single ride costs at most $25.00."""

LOST_BIKE_FEE = Decimal("100.00")
"""F-011: a ride closed as lost is charged a $100.00 lost-bike fee."""


def price_ride(
    is_member: bool,
    minutes: Decimal,
    is_ebike: bool,
    ebike_surcharge_enabled: bool,
    surge_multiplier: Decimal = Decimal("1"),
) -> int:
    """The ride charge in integer cents.

    F-025: the single-ride cap applies to the ride charge including the
    e-bike surcharge. The charge is the unlock fee (casual riders only)
    plus charged minutes times the per-minute rate times the surge
    multiplier, plus charged e-bike minutes times the surcharge, capped at
    SINGLE_RIDE_CAP.
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

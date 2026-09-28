"""Farebox per-minute rates, the e-bike surcharge and the single-ride cap."""

from __future__ import annotations

from decimal import Decimal

import pytest

from farebox.pricing import (
    CASUAL_RATE,
    EBIKE_SURCHARGE,
    MEMBER_FREE_MINUTES,
    MEMBER_RATE,
    SINGLE_RIDE_CAP,
    price_ride,
)


@pytest.mark.unit
def test_member_rate_after_free_minutes():
    """F-005: a member pays $0.15 per minute for every minute after the
    free minutes."""
    assert MEMBER_RATE == Decimal("0.15")
    minutes = Decimal(MEMBER_FREE_MINUTES + 10)
    amount_cents = price_ride(True, minutes, False, False)
    assert amount_cents == 150


@pytest.mark.unit
def test_casual_rate_from_first_minute():
    """F-006: a rider without a membership pays $0.25 per minute from the
    first minute of the ride."""
    assert CASUAL_RATE == Decimal("0.25")
    amount_cents = price_ride(False, Decimal("10"), False, False)
    assert amount_cents == 350


@pytest.mark.unit
def test_ebike_surcharge_when_flag_on():
    """F-007: when the ebike_surcharge flag is on, every charged minute of
    an e-bike ride costs an extra $0.10."""
    assert EBIKE_SURCHARGE == Decimal("0.10")
    with_flag = price_ride(False, Decimal("10"), True, True)
    without_flag = price_ride(False, Decimal("10"), True, False)
    assert with_flag - without_flag == 100


@pytest.mark.unit
def test_single_ride_cap_25():
    """F-008: a single ride costs at most $25.00."""
    assert SINGLE_RIDE_CAP == Decimal("25.00")
    amount_cents = price_ride(False, Decimal("1000"), False, False)
    assert amount_cents == 2500

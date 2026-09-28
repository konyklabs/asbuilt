"""Rate, surcharge and clamp behaviour of price_ride."""

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
    """Duration picked ten units past the configured threshold, so only
    the excess portion should factor into the total."""
    assert MEMBER_RATE == Decimal("0.15")
    minutes = Decimal(MEMBER_FREE_MINUTES + 10)
    amount_cents = price_ride(True, minutes, False, False)
    assert amount_cents == 150


@pytest.mark.unit
def test_casual_rate_from_first_minute():
    """Ten-minute casual ride: no free window to subtract first."""
    assert CASUAL_RATE == Decimal("0.25")
    amount_cents = price_ride(False, Decimal("10"), False, False)
    assert amount_cents == 350


@pytest.mark.unit
def test_ebike_surcharge_when_flag_on():
    """Same e-bike ride priced with the add-on toggled each way."""
    assert EBIKE_SURCHARGE == Decimal("0.10")
    with_flag = price_ride(False, Decimal("10"), True, True)
    without_flag = price_ride(False, Decimal("10"), True, False)
    assert with_flag - without_flag == 100


@pytest.mark.unit
def test_single_ride_cap_25():
    """Deliberately long ride: the clamp, not the rate, sets the price."""
    assert SINGLE_RIDE_CAP == Decimal("25.00")
    amount_cents = price_ride(False, Decimal("1000"), False, False)
    assert amount_cents == 2500

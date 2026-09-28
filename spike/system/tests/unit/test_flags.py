"""Feature flag defaults."""

from __future__ import annotations

import pytest

from farebox.flags import FLAGS


@pytest.mark.unit
def test_dynamic_pricing_off_by_default():
    """F-049: the dynamic_pricing flag is off by default."""
    assert FLAGS["dynamic_pricing"] is False

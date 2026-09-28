"""Registered flag defaults."""

from __future__ import annotations

import pytest

from farebox.flags import FLAGS


@pytest.mark.unit
def test_dynamic_pricing_off_by_default():
    """Reading the registry before any override is ever applied."""
    assert FLAGS["dynamic_pricing"] is False

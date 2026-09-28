"""Dock model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Dock:
    """One parking slot; `bike_id` is None while the slot sits empty."""

    id: str
    station_id: str
    bike_id: str | None
    state: str

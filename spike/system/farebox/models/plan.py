"""Plan model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Plan:
    """A membership plan: id, name, price_cents, interval."""

    id: str
    name: str
    price_cents: int
    interval: str

"""Seeds the plans table."""

from __future__ import annotations

PLANS = [
    {"id": "plan-monthly", "name": "monthly", "price_cents": 1500, "interval": "month"},
    {"id": "plan-annual", "name": "annual", "price_cents": 12000, "interval": "year"},
]
"""F-030: the monthly plan costs $15.00 per month and the annual plan
costs $120.00 per year."""

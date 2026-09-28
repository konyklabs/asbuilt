"""Seeds the plans table."""

from __future__ import annotations

PLANS = [
    {"id": "plan-monthly", "name": "monthly", "price_cents": 1500, "interval": "month"},
    {"id": "plan-annual", "name": "annual", "price_cents": 12000, "interval": "year"},
]
# Row payloads inserted by the seed step, one per selectable plan.

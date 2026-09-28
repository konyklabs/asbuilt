"""Creates the farebox tables and feature_flags."""

from __future__ import annotations


def upgrade() -> list[dict[str, object]]:
    """Return the schema this migration creates, as a list of
    {table, columns} dicts, one per table."""
    return [
        {"table": "riders", "columns": ["id", "name", "email"]},
        {"table": "plans", "columns": ["id", "name", "price_cents", "interval"]},
        {
            "table": "memberships",
            "columns": ["id", "rider_id", "plan_id", "status", "renews_at", "grace_ends_at"],
        },
        {"table": "invoices", "columns": ["id", "rider_id", "period_start", "period_end"]},
        {"table": "invoice_lines", "columns": ["id", "invoice_id", "ride_id", "amount_cents"]},
        {"table": "payments", "columns": ["id", "ride_id", "amount_cents", "status"]},
        {"table": "refunds", "columns": ["id", "ride_id", "amount_cents", "status"]},
        {"table": "feature_flags", "columns": ["name", "enabled"]},
    ]

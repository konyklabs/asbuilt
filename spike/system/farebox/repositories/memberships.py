"""Membership queries."""

from __future__ import annotations

from farebox.models.membership import Membership


class MembershipRepository:
    """CRUD and lookups over an in-memory table of Membership rows."""

    def __init__(self, rows: dict[str, Membership] | None = None) -> None:
        self._rows: dict[str, Membership] = rows if rows is not None else {}

    def add(self, membership: Membership) -> None:
        self._rows[membership.id] = membership

    def get(self, membership_id: str) -> Membership | None:
        return self._rows.get(membership_id)

    def for_rider(self, rider_id: str) -> Membership | None:
        for membership in self._rows.values():
            if membership.rider_id == rider_id:
                return membership
        return None

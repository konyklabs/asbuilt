"""Database session helper.

farebox owns riders, plans, memberships, invoices, invoice_lines,
payments, refunds and feature_flags; this module stands in for a real
database connection with a process-memory store, and a session_scope()
context manager that mirrors the shape callers would use against a real
database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from farebox.models.invoice import Invoice, InvoiceLine
from farebox.models.membership import Membership
from farebox.models.payment import Payment
from farebox.models.plan import Plan
from farebox.models.refund import Refund
from farebox.models.rider import Rider
from farebox.repositories.invoices import InvoiceRepository
from farebox.repositories.memberships import MembershipRepository
from farebox.repositories.payments import PaymentRepository
from farebox.repositories.refunds import RefundRepository
from farebox.repositories.riders import RiderRepository


@dataclass
class Store:
    """The process-memory tables farebox writes to."""

    riders: dict[str, Rider] = field(default_factory=dict)
    plans: dict[str, Plan] = field(default_factory=dict)
    memberships: dict[str, Membership] = field(default_factory=dict)
    invoices: dict[str, Invoice] = field(default_factory=dict)
    invoice_lines: dict[str, InvoiceLine] = field(default_factory=dict)
    payments: dict[str, Payment] = field(default_factory=dict)
    refunds: dict[str, Refund] = field(default_factory=dict)
    feature_flags: dict[str, bool] = field(default_factory=dict)


@dataclass
class Session:
    """A bundle of repositories bound to one in-memory Store."""

    riders: RiderRepository
    memberships: MembershipRepository
    invoices: InvoiceRepository
    payments: PaymentRepository
    refunds: RefundRepository


def build_session(store: Store) -> Session:
    """Wire a Session's repositories to `store`'s tables."""
    return Session(
        riders=RiderRepository(store.riders),
        memberships=MembershipRepository(store.memberships),
        invoices=InvoiceRepository(store.invoices, store.invoice_lines),
        payments=PaymentRepository(store.payments),
        refunds=RefundRepository(store.refunds),
    )


@contextmanager
def session_scope(store: Store | None = None) -> Iterator[Session]:
    """Yield a Session of repositories bound to `store` (or a fresh Store).

    There is no real transaction to commit or roll back; the context
    manager exists so callers acquire and release a session the same way
    they would against a real database.
    """
    yield build_session(store if store is not None else Store())

"""Application factory."""

from __future__ import annotations

from dataclasses import dataclass

from farebox.clients.tollbooth import TollboothClient, Transport
from farebox.db import Session, Store, build_session
from farebox.events import EventBus
from farebox.flags import FlagCache


@dataclass
class App:
    """A wired farebox app: its session, event bus, flag cache and
    Tollbooth Pay client."""

    session: Session
    bus: EventBus
    flags: FlagCache
    tollbooth: TollboothClient


def create_app(tollbooth_transport: Transport, store: Store | None = None) -> App:
    """Build a farebox App bound to one in-memory store."""
    store = store if store is not None else Store()
    return App(
        session=build_session(store),
        bus=EventBus(),
        flags=FlagCache(lambda: dict(store.feature_flags)),
        tollbooth=TollboothClient(tollbooth_transport),
    )

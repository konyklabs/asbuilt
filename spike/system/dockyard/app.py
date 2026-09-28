"""Application factory; mounts the routers.

dockyard has no real HTTP server in this fixture: `create_app` wires the
in-memory session, the flag cache and the farebox client into one App so
tests and the api-layer functions can use them as plain values.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from dockyard.clients.farebox import FareboxClient, Transport
from dockyard.db import Session, Store, build_session
from dockyard.flags import FlagCache


@dataclass
class App:
    """A wired dockyard app: its session, flag cache and farebox client."""

    session: Session
    flags: FlagCache
    farebox: FareboxClient


def create_app(
    farebox_transport: Transport,
    read_flags: Callable[[], dict[str, bool]],
    store: Store | None = None,
) -> App:
    """Build a dockyard App bound to one in-memory store."""
    store = store if store is not None else Store()
    return App(
        session=build_session(store),
        flags=FlagCache(read_flags),
        farebox=FareboxClient(farebox_transport),
    )

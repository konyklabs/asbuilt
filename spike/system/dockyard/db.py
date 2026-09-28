"""Database session helper.

dockyard owns stations, docks, bikes and rides; this module stands in for
a real database connection with a process-memory store, and a
session_scope() context manager that mirrors the shape callers would use
against a real database.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from dockyard.models.bike import Bike
from dockyard.models.dock import Dock
from dockyard.models.ride import Ride
from dockyard.models.station import Station
from dockyard.repositories.bikes import BikeRepository
from dockyard.repositories.docks import DockRepository
from dockyard.repositories.rides import RideRepository
from dockyard.repositories.stations import StationRepository


@dataclass
class Store:
    """The process-memory tables dockyard writes to."""

    stations: dict[str, Station] = field(default_factory=dict)
    docks: dict[str, Dock] = field(default_factory=dict)
    bikes: dict[str, Bike] = field(default_factory=dict)
    rides: dict[str, Ride] = field(default_factory=dict)


@dataclass
class Session:
    """A bundle of repositories bound to one in-memory Store."""

    stations: StationRepository
    docks: DockRepository
    bikes: BikeRepository
    rides: RideRepository


def build_session(store: Store) -> Session:
    """Wire a Session's repositories to `store`'s tables."""
    return Session(
        stations=StationRepository(store.stations),
        docks=DockRepository(store.docks),
        bikes=BikeRepository(store.bikes),
        rides=RideRepository(store.rides),
    )


@contextmanager
def session_scope(store: Store | None = None) -> Iterator[Session]:
    """Yield a Session of repositories bound to `store` (or a fresh Store).

    There is no real transaction to commit or roll back; the context
    manager exists so callers acquire and release a session the same way
    they would against a real database.
    """
    yield build_session(store if store is not None else Store())

"""Seeds stations for local development."""

from __future__ import annotations

from dockyard.db import Store, session_scope
from dockyard.models.station import Station


def main(store: Store | None = None) -> None:
    """Seed a handful of stations for local development."""
    with session_scope(store) as session:
        for i in range(1, 6):
            session.stations.add(
                Station(
                    id=f"station-{i}",
                    name=f"Station {i}",
                    capacity=20,
                    lat=40.0 + i,
                    lon=-73.9 + i,
                )
            )


if __name__ == "__main__":
    main()

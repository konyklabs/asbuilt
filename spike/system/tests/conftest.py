"""Shared fixtures wiring dockyard and farebox together in-process."""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pytest

from dockyard.app import App as DockyardApp
from dockyard.app import create_app as create_dockyard_app
from dockyard.db import Store as DockyardStore
from farebox.api.rides import close_ride_endpoint
from farebox.app import App as FareboxApp
from farebox.app import create_app as create_farebox_app
from farebox.db import Store as FareboxStore
from farebox.flags import is_enabled


def _current_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return result.stdout.strip()


def pytest_json_modifyreport(json_report):
    """Record the commit and step a run was executed against, so the
    harness can attribute a run to the tree it ran against."""
    json_report["metadata"] = {
        "commit": _current_commit(),
        "step": os.environ.get("GEARWELL_STEP"),
    }


@dataclass
class System:
    """Both services, wired together for an end-to-end test."""

    dockyard: DockyardApp
    farebox: FareboxApp


def _farebox_transport_for(farebox_app: FareboxApp):
    """A dockyard->farebox transport that calls farebox's own endpoint
    functions in-process, standing in for the wire call between the two
    services (F-055)."""

    def transport(method: str, path: str, body: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        if method == "POST" and path.startswith("/internal/rides/") and path.endswith("/close"):
            ride_id = path.removeprefix("/internal/rides/").removesuffix("/close")
            return close_ride_endpoint(
                farebox_app.session,
                farebox_app.bus,
                farebox_app.tollbooth,
                ride_id,
                body["rider_id"],
                body["bike_id"],
                body["return_station_id"],
                body["is_ebike"],
                datetime.fromisoformat(body["started_at"]),
                datetime.fromisoformat(body["ended_at"]),
                is_enabled(farebox_app.flags, "ebike_surcharge"),
                is_enabled(farebox_app.flags, "dynamic_pricing"),
                None,
            )
        raise ValueError(f"unhandled transport call: {method} {path}")

    return transport


@pytest.fixture
def system() -> System:
    """A fresh dockyard app and farebox app, wired together, each backed
    by its own empty in-memory store. Tollbooth Pay always succeeds
    unless a test replaces the client."""
    farebox_store = FareboxStore()
    farebox_app = create_farebox_app(
        tollbooth_transport=lambda ride_id, amount_cents: (200, False),
        store=farebox_store,
    )
    dockyard_app = create_dockyard_app(
        farebox_transport=_farebox_transport_for(farebox_app),
        read_flags=lambda: dict(farebox_store.feature_flags),
        store=DockyardStore(),
    )
    return System(dockyard=dockyard_app, farebox=farebox_app)

"""Serves the rider portal's pages and its /api routes over HTTP.

Run from the repository root, with the root on the import path:

    PYTHONPATH=. python web/serve.py --backend real --port 4303

`--backend real` answers /api from dockyard and farebox, wired in this one
process; `fake` answers farebox's routes from fake_farebox.py instead; `none`
answers no /api route at all, for a browser that intercepts them itself.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from fake_farebox import FakeFarebox

from dockyard.api.rides import checkout_endpoint
from dockyard.app import create_app as create_dockyard_app
from dockyard.db import Store as DockyardStore
from dockyard.models.bike import Bike, BikeKind
from farebox.api.refunds import create_refund_endpoint
from farebox.app import create_app as create_farebox_app
from farebox.db import Store as FareboxStore
from farebox.flags import is_enabled
from farebox.pricing import price_ride

PUBLIC = Path(__file__).resolve().parent / "public"
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8"}
SEEDED_BIKES = 6

Route = Callable[[dict[str, str], dict[str, Any]], tuple[int, dict[str, Any]]]
Routes = dict[tuple[str, str], Route]


def _seeded_dockyard_store() -> DockyardStore:
    store = DockyardStore()
    for n in range(1, SEEDED_BIKES + 1):
        store.bikes[f"bike-{n}"] = Bike(id=f"bike-{n}", kind=BikeKind.CLASSIC)
    return store


def _no_farebox_calls(method: str, path: str, body: dict[str, Any]):
    raise ValueError(f"the portal never closes rides: {method} {path}")


def route_api(backend: str) -> Routes:
    """The /api routes for one backend, keyed by (method, path)."""
    if backend == "none":
        return {}

    farebox_store = FareboxStore()
    farebox = create_farebox_app(
        tollbooth_transport=lambda ride_id, amount_cents: (200, False), store=farebox_store
    )
    dockyard = create_dockyard_app(
        farebox_transport=_no_farebox_calls,
        read_flags=lambda: dict(farebox_store.feature_flags),
        store=_seeded_dockyard_store(),
    )

    def check_out(_query, payload):
        return checkout_endpoint(
            dockyard.session,
            payload["rider_id"],
            payload["bike_id"],
            payload["station_id"],
            datetime.now(UTC),
        )

    def preview_fare(query, _payload):
        cents = price_ride(
            query.get("member") == "1",
            Decimal(query["minutes"]),
            query.get("ebike") == "1",
            is_enabled(farebox.flags, "ebike_surcharge"),
        )
        return 200, {"amount_cents": cents}

    def request_refund(_query, payload):
        return create_refund_endpoint(
            farebox.session,
            payload["ride_id"],
            datetime.fromisoformat(payload["ride_ended_at"]),
            payload["charged_cents"],
            payload["requested_cents"],
            datetime.now(UTC),
            auto_approve_enabled=is_enabled(farebox.flags, "refund_auto_approve"),
        )

    routes: Routes = {
        ("POST", "/api/rides/checkout"): check_out,
        ("GET", "/api/fares/preview"): preview_fare,
        ("POST", "/api/refunds"): request_refund,
    }
    if backend == "fake":
        fake = FakeFarebox()
        routes[("GET", "/api/fares/preview")] = fake.preview_fare
        routes[("POST", "/api/refunds")] = fake.request_refund
    return routes


class PortalHandler(BaseHTTPRequestHandler):
    routes: Routes = {}

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def _dispatch(self, method: str) -> None:
        url = urlsplit(self.path)
        if url.path.startswith("/api/"):
            route = self.routes.get((method, url.path))
            if route is None:
                self._send_json(503, {"error": "no_backend_route"})
                return
            query = {key: values[-1] for key, values in parse_qs(url.query).items()}
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length)) if length else {}
            self._send_json(*route(query, payload))
            return
        if method != "GET":
            self._send_json(405, {"error": "method_not_allowed"})
            return
        self._send_page(url.path)

    def _send_page(self, path: str) -> None:
        target = (PUBLIC / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(PUBLIC) or not target.is_file():
            self._send_json(404, {"error": "not_found"})
            return
        content_type = CONTENT_TYPES.get(target.suffix, "application/octet-stream")
        self._send(200, content_type, target.read_bytes())

    def _send_json(self, status: int, body: dict[str, Any]) -> None:
        self._send(status, "application/json", json.dumps(body).encode())

    def _send(self, status: int, content_type: str, data: bytes) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backend", choices=("real", "fake", "none"), default="real")
    parser.add_argument("--port", type=int, default=4303)
    args = parser.parse_args(argv)

    PortalHandler.routes = route_api(args.backend)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), PortalHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

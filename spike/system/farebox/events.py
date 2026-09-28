"""Publishes to ride.events."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from farebox.models.refund import Refund

RIDE_EVENTS_TOPIC = "ride.events"
# Message bus topic this module writes both event kinds below onto.


@dataclass
class EventBus:
    """A minimal in-process pub/sub bus standing in for ride.events."""

    published: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    _subscribers: list[Callable[[str, dict[str, Any]], None]] = field(default_factory=list)

    def publish(self, topic: str, payload: dict[str, Any]) -> None:
        self.published.append((topic, payload))
        for subscriber in self._subscribers:
            subscriber(topic, payload)

    def subscribe(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        self._subscribers.append(handler)


def publish_ride_completed(
    bus: EventBus,
    ride_id: str,
    rider_id: str,
    bike_id: str,
    return_station_id: str,
    ended_at: datetime,
    amount_cents: int,
) -> None:
    """Build and publish the payload a closed ride reports downstream."""
    bus.publish(
        RIDE_EVENTS_TOPIC,
        {
            "type": "ride.completed",
            "ride_id": ride_id,
            "rider_id": rider_id,
            "bike_id": bike_id,
            "return_station_id": return_station_id,
            "ended_at": ended_at.isoformat(),
            "amount_cents": amount_cents,
        },
    )


def publish_ride_refunded(bus: EventBus, refund: Refund) -> None:
    """Build and publish the payload a paid refund reports downstream."""
    bus.publish(
        RIDE_EVENTS_TOPIC,
        {
            "type": "ride.refunded",
            "ride_id": refund.ride_id,
            "refund_id": refund.id,
            "amount_cents": refund.amount_cents,
        },
    )

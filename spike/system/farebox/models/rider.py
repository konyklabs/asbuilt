"""Rider model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Rider:
    """A rider: id, name, email."""

    id: str
    name: str
    email: str

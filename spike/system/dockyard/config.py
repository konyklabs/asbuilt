"""Settings for the dockyard service, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Dockyard's environment-derived configuration."""

    database_url: str = "sqlite:///:memory:"
    farebox_base_url: str = "http://farebox.internal"

    @classmethod
    def from_env(cls) -> Settings:
        """Build Settings, falling back to the defaults above."""
        return cls(
            database_url=os.environ.get("DOCKYARD_DATABASE_URL", cls.database_url),
            farebox_base_url=os.environ.get("FAREBOX_BASE_URL", cls.farebox_base_url),
        )

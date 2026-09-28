"""Settings for the farebox service, read from the environment."""

from __future__ import annotations

import os
from dataclasses import dataclass

TOLLBOOTH_TIMEOUT_SECONDS = 5  # seconds


@dataclass(frozen=True)
class Settings:
    """Farebox's environment-derived configuration."""

    database_url: str = "sqlite:///:memory:"
    tollbooth_base_url: str = "https://api.tollboothpay.invalid"

    @classmethod
    def from_env(cls) -> Settings:
        """Build Settings, falling back to the defaults above."""
        return cls(
            database_url=os.environ.get("FAREBOX_DATABASE_URL", cls.database_url),
            tollbooth_base_url=os.environ.get("TOLLBOOTH_BASE_URL", cls.tollbooth_base_url),
        )

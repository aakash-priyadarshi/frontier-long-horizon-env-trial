"""V2 runtime settings loaded without exposing secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse, urlunparse


def dashboard_origins(origin: str) -> tuple[str, ...]:
    """Return the configured dashboard origin and its intentional loopback alias."""
    configured = origin.rstrip("/")
    origins = {configured}
    parsed = urlparse(configured)
    if parsed.scheme in {"http", "https"} and parsed.hostname in {"localhost", "127.0.0.1"}:
        alternate = "127.0.0.1" if parsed.hostname == "localhost" else "localhost"
        netloc = alternate + (f":{parsed.port}" if parsed.port else "")
        origins.add(urlunparse((parsed.scheme, netloc, "", "", "", "")))
    return tuple(sorted(origins))


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    database_path: Path
    event_replay_limit: int = 1_000
    dashboard_origin: str = "http://localhost:3000"
    local_env_path: Path | None = None
    provider_state_path: Path | None = None
    talon_data_dir: Path | None = None
    talon_database_path: Path | None = None
    talon_retention_days: int = 0

    @classmethod
    def from_environment(cls) -> "Settings":
        data_dir = Path(os.getenv("FRONTIER_DATA_DIR", ".frontier"))
        return cls(
            data_dir=data_dir,
            database_path=Path(os.getenv("FRONTIER_DATABASE_PATH", data_dir / "evaluations.sqlite3")),
            event_replay_limit=max(100, int(os.getenv("FRONTIER_EVENT_REPLAY_LIMIT", "1000"))),
            dashboard_origin=os.getenv("FRONTIER_DASHBOARD_ORIGIN", "http://localhost:3000"),
            local_env_path=Path(os.getenv("FRONTIER_ENV_PATH", ".env")),
            provider_state_path=Path(
                os.getenv("FRONTIER_PROVIDER_STATE_PATH", data_dir / "provider-state.json")
            ),
            talon_data_dir=Path(os.getenv("TALON_DATA_DIR", data_dir / "talon")),
            talon_database_path=Path(
                os.getenv("TALON_DATABASE_PATH", data_dir / "talon" / "talon.sqlite3")
            ),
            talon_retention_days=max(0, int(os.getenv("TALON_RETENTION_DAYS", "0"))),
        )

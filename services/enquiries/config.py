"""Configuration of the enquiries service, resolved entirely from environment
variables.

Every setting has a working default, so the service starts with no .env file
and no source edits. This file is a copy-and-trim of the monolith's config.py:
each service keeps its own, so none of them imports another's (ADR-6).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Binding to 0.0.0.0 rather than localhost is a deployment requirement: inside
# a container, a process bound to the loopback interface is unreachable.
BIND_HOST = "0.0.0.0"

DEFAULT_PORT = 8000
DEFAULT_DATA_DIR = "data"
DATABASE_FILENAME = "enquiries.db"


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of the environment, read once at startup."""

    host: str
    port: int
    data_dir: Path
    debug: bool
    # Excluded from repr, so printing or logging a Config never reveals it.
    # None means the staff endpoints are switched off; see security.py.
    admin_password: str | None = field(default=None, repr=False)

    @property
    def database_path(self) -> Path:
        return self.data_dir / DATABASE_FILENAME


def load_config() -> Config:
    """Build a Config from os.environ, falling back to defaults throughout."""
    return Config(
        host=BIND_HOST,
        port=_read_port(),
        data_dir=Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR).resolve(),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        admin_password=os.environ.get("ADMIN_PASSWORD") or None,
    )


def _read_port() -> int:
    """Parse PORT; a malformed value falls back to the default rather than
    stopping an unattended start over a typo."""
    raw = os.environ.get("PORT", "").strip()
    if not raw:
        return DEFAULT_PORT
    try:
        port = int(raw)
    except ValueError:
        logger.warning("PORT=%r is not an integer; using %d", raw, DEFAULT_PORT)
        return DEFAULT_PORT
    if not 1 <= port <= 65535:
        logger.warning("PORT=%d is out of range; using %d", port, DEFAULT_PORT)
        return DEFAULT_PORT
    return port

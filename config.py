"""Application configuration, resolved entirely from environment variables.

The deployment contract for this project requires that the app be
reconfigurable without editing source and without a .env file existing, so
every setting here has a working default. Nothing in this module reads from
disk or the network, which keeps startup within the required few seconds.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Binding to 0.0.0.0 rather than localhost is a deployment requirement: inside
# a container, a process bound to the loopback interface is unreachable.
BIND_HOST = "0.0.0.0"

DEFAULT_PORT = 8000
DEFAULT_DATA_DIR = "data"
DATABASE_FILENAME = "alrahmeh.db"


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of the environment, read once at startup."""

    host: str
    port: int
    data_dir: Path
    debug: bool
    # One shared secret for the staff-only endpoints. None means admin access is
    # switched off entirely; see security.require_admin for why that is the
    # default rather than a built-in password.
    admin_password: str | None = None

    @property
    def database_path(self) -> Path:
        """The single documented location of the SQLite file."""
        return self.data_dir / DATABASE_FILENAME


def load_config() -> Config:
    """Build a Config from os.environ, falling back to defaults throughout."""
    return Config(
        host=BIND_HOST,
        port=_read_port(),
        data_dir=Path(os.environ.get("DATA_DIR") or DEFAULT_DATA_DIR).resolve(),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        # Deliberately no default: an unset ADMIN_PASSWORD disables the staff
        # endpoints rather than falling back to a value an attacker could guess.
        admin_password=os.environ.get("ADMIN_PASSWORD") or None,
    )


def _read_port() -> int:
    """Parse PORT, ignoring values that are not usable TCP port numbers.

    A malformed PORT falls back to the default rather than raising: the
    deployment script starts this process unattended, so refusing to boot over
    a bad environment variable would turn a typo into an outage.
    """
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

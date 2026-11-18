"""Configuration of the animals service, resolved entirely from environment
variables.

Every setting has a working default, so the service starts with no .env file
and no source edits. Nothing here reads from disk or the network, which keeps
startup fast. This file is a copy-and-trim of the monolith's config.py: each
service keeps its own, so none of them imports another's (ADR-6).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Binding to 0.0.0.0 rather than localhost is a deployment requirement: inside
# a container, a process bound to the loopback interface is unreachable.
BIND_HOST = "0.0.0.0"

SERVICE = "animals"
DEFAULT_PORT = 8000


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of the environment, read once at startup."""

    host: str
    port: int
    debug: bool
    # Secrets are excluded from repr, so printing or logging a Config never
    # reveals them.
    # mssql://USER:PASSWORD@HOST:PORT/DATABASE[?encrypt=true]; see db.py. No
    # default: it holds a password, so there is nothing safe to fall back to.
    database_url: str | None = field(default=None, repr=False)
    # None means the staff endpoints are switched off; see security.py.
    admin_password: str | None = field(default=None, repr=False)
    # Add sample animals at startup when there are none. Off unless asked for,
    # so a Config built directly (as every test does) starts empty; the
    # environment default in load_config turns it on.
    sample_animals: bool = False
    service: str = SERVICE


def load_config() -> Config:
    """Build a Config from os.environ, falling back to defaults throughout."""
    return Config(
        host=BIND_HOST,
        port=_read_port(),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        database_url=os.environ.get("DATABASE_URL") or None,
        # Deliberately no default: unset disables the staff endpoints rather
        # than falling back to a value an attacker could guess.
        admin_password=os.environ.get("ADMIN_PASSWORD") or None,
        sample_animals=os.environ.get("SAMPLE_ANIMALS", "1").strip() != "0",
    )


def _read_port() -> int:
    """Parse PORT, ignoring values that are not usable TCP port numbers.

    A malformed PORT falls back to the default rather than raising: the
    service is started unattended, so refusing to boot over a bad environment
    variable would turn a typo into an outage.
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

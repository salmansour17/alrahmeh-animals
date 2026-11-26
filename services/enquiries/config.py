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
from urllib.parse import urlsplit

from hardening import HardeningSettings

logger = logging.getLogger(__name__)

# Binding to 0.0.0.0 rather than localhost is a deployment requirement: inside
# a container, a process bound to the loopback interface is unreachable.
BIND_HOST = "0.0.0.0"

SERVICE = "enquiries"
DEFAULT_PORT = 8000
DEFAULT_VERSION = "dev"


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
    # Website origins allowed to call this service from a browser (cors.py).
    cors_origins: frozenset[str] = frozenset()
    # The git commit this build came from, set at image build time (GIT_SHA);
    # "dev" when running from a checkout. Reported by GET /health.
    version: str = DEFAULT_VERSION
    service: str = SERVICE
    # Rate limits and the trusted proxy count (hardening.py); the defaults
    # unless the environment says otherwise.
    hardening: HardeningSettings = HardeningSettings()


def load_config() -> Config:
    """Build a Config from os.environ, falling back to defaults throughout."""
    return Config(
        host=BIND_HOST,
        port=_read_port(),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
        database_url=os.environ.get("DATABASE_URL") or None,
        admin_password=os.environ.get("ADMIN_PASSWORD") or None,
        cors_origins=_read_cors_origins(),
        version=os.environ.get("GIT_SHA", "").strip() or DEFAULT_VERSION,
        # Raises on a nonsense value, which stops the start (fail fast).
        hardening=HardeningSettings.from_environment(),
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


def _read_cors_origins() -> frozenset[str]:
    """Parse CORS_ORIGINS: website origins allowed to call this service,
    comma separated, e.g. https://alrahmehui.z28.web.core.windows.net.

    Each must be a plain http(s) origin. A wildcard or anything malformed is
    dropped with a warning rather than widened or guessed at; unset means no
    other origin may call this service from a browser.
    """
    origins = set()
    for raw in os.environ.get("CORS_ORIGINS", "").split(","):
        candidate = raw.strip().removesuffix("/")
        if not candidate:
            continue
        if candidate == "*" or not _is_plain_origin(candidate):
            logger.warning("CORS_ORIGINS entry %r is not a plain http(s) origin; ignored", raw.strip())
            continue
        origins.add(candidate)
    return frozenset(origins)


def _is_plain_origin(candidate: str) -> bool:
    """http(s), a host, an optional port, and nothing else."""
    parts = urlsplit(candidate)
    return (
        parts.scheme in ("http", "https")
        and bool(parts.hostname)
        and "@" not in parts.netloc
        and not parts.path
        and not parts.query
        and not parts.fragment
    )

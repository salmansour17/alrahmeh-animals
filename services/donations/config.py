"""Configuration of the donations service, resolved entirely from environment
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
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Binding to 0.0.0.0 rather than localhost is a deployment requirement: inside
# a container, a process bound to the loopback interface is unreachable.
BIND_HOST = "0.0.0.0"

SERVICE = "donations"
DEFAULT_PORT = 8000
DEFAULT_VERSION = "dev"
# Where donors are sent back to after Stripe Checkout: the UI's origin, not this
# service's. The default is the Vite dev server; a deployment sets the static
# website's address.
DEFAULT_PUBLIC_BASE_URL = "http://localhost:5173"
# Where the animals service answers. The default is its name inside Docker
# Compose; running outside Compose, set ANIMALS_URL (e.g. http://localhost:8001).
DEFAULT_ANIMALS_URL = "http://animals:8000"
# Every call to the animals service gives up after this many seconds, so a slow
# or stopped animals service can never hang a request here.
DEFAULT_ANIMALS_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of the environment, read once at startup."""

    host: str
    port: int
    debug: bool
    # Secrets are excluded from repr, so printing or logging a Config (or a test
    # failure that shows one) can never reveal them.
    # mssql://USER:PASSWORD@HOST:PORT/DATABASE[?encrypt=true]; see db.py. No
    # default: it holds a password, so there is nothing safe to fall back to.
    database_url: str | None = field(default=None, repr=False)
    # None means the staff endpoints are switched off; see security.py.
    admin_password: str | None = field(default=None, repr=False)
    # Stripe. None for either secret means the payment endpoints answer 503.
    stripe_secret_key: str | None = field(default=None, repr=False)
    stripe_webhook_secret: str | None = field(default=None, repr=False)
    # None when PUBLIC_BASE_URL was set but invalid: payments are then disabled
    # rather than sending donors somewhere unintended.
    public_base_url: str | None = DEFAULT_PUBLIC_BASE_URL
    # Ways to give without a card, shown on the donate page. Public details,
    # not secrets, but they belong to the rescue, so they come from the
    # environment and never from source. Unset means that option is hidden.
    cliq_alias: str | None = None
    bank_name: str | None = None
    bank_iban: str | None = None
    bank_account_name: str | None = None
    animals_url: str = DEFAULT_ANIMALS_URL
    animals_timeout_s: float = DEFAULT_ANIMALS_TIMEOUT_S
    # Website origins allowed to call this service from a browser (cors.py).
    cors_origins: frozenset[str] = frozenset()
    # The git commit this build came from, set at image build time (GIT_SHA);
    # "dev" when running from a checkout. Reported by GET /health.
    version: str = DEFAULT_VERSION
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
        cors_origins=_read_cors_origins(),
        version=os.environ.get("GIT_SHA", "").strip() or DEFAULT_VERSION,
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY") or None,
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET") or None,
        public_base_url=_read_public_base_url(),
        cliq_alias=_read_optional("CLIQ_ALIAS"),
        bank_name=_read_optional("BANK_NAME"),
        bank_iban=_read_optional("BANK_IBAN"),
        bank_account_name=_read_optional("BANK_ACCOUNT_NAME"),
        animals_url=_read_animals_url(),
        animals_timeout_s=_read_timeout("ANIMALS_TIMEOUT_S", DEFAULT_ANIMALS_TIMEOUT_S),
    )


def _read_optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


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


def _read_public_base_url() -> str | None:
    """Parse PUBLIC_BASE_URL: http(s), a host, and nothing else.

    Stripe sends donors back to this address after they pay, so it must be
    exactly the site's own origin. A path, query, fragment or user@ prefix is
    rejected rather than tidied up. Unlike a bad PORT this does not fall back to
    the default: falling back to localhost would strand every donor on a dead
    page after paying, so an invalid value disables payments (None) instead.
    """
    raw = os.environ.get("PUBLIC_BASE_URL", "").strip()
    if not raw:
        return DEFAULT_PUBLIC_BASE_URL
    candidate = raw.removesuffix("/")
    if not _is_plain_origin(candidate):
        logger.warning("PUBLIC_BASE_URL=%r is not a plain http(s) origin; payments disabled", raw)
        return None
    return candidate


def _read_animals_url() -> str:
    """Parse ANIMALS_URL. A malformed value falls back to the default and is
    logged: the earmark check then fails in its designed way (the animals
    service counts as unreachable) instead of the service refusing to start."""
    raw = os.environ.get("ANIMALS_URL", "").strip()
    if not raw:
        return DEFAULT_ANIMALS_URL
    candidate = raw.removesuffix("/")
    if not _is_plain_origin(candidate):
        logger.warning("ANIMALS_URL=%r is not a plain http(s) origin; using %s", raw, DEFAULT_ANIMALS_URL)
        return DEFAULT_ANIMALS_URL
    return candidate


def _read_timeout(name: str, default: float) -> float:
    """A positive number of seconds; anything else falls back to the default,
    because an unbounded or zero timeout would defeat its purpose."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        seconds = float(raw)
    except ValueError:
        logger.warning("%s=%r is not a number; using %s", name, raw, default)
        return default
    if not 0 < seconds <= 60:
        logger.warning("%s=%s is out of range (0-60]; using %s", name, raw, default)
        return default
    return seconds


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

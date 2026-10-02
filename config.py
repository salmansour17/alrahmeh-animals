"""Application configuration, resolved entirely from environment variables.

The deployment contract for this project requires that the app be
reconfigurable without editing source and without a .env file existing, so
every setting here has a working default. Nothing in this module reads from
disk or the network, which keeps startup within the required few seconds.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Binding to 0.0.0.0 rather than localhost is a deployment requirement: inside
# a container, a process bound to the loopback interface is unreachable.
BIND_HOST = "0.0.0.0"

DEFAULT_PORT = 8000
DEFAULT_DATA_DIR = "data"
DATABASE_FILENAME = "alrahmeh.db"
PHOTOS_DIRNAME = "photos"
# Where donors are sent back to after Stripe Checkout. Local development
# default; a deployment sets PUBLIC_BASE_URL to its real address.
DEFAULT_PUBLIC_BASE_URL = "http://localhost:8000"


@dataclass(frozen=True)
class Config:
    """Immutable snapshot of the environment, read once at startup."""

    host: str
    port: int
    data_dir: Path
    debug: bool
    # Secrets are excluded from repr, so printing or logging a Config (or a test
    # failure that shows one) can never reveal them.
    #
    # One shared secret for the staff-only endpoints. None means admin access is
    # switched off entirely; see security.require_admin for why that is the
    # default rather than a built-in password.
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

    @property
    def database_path(self) -> Path:
        """The single documented location of the SQLite file."""
        return self.data_dir / DATABASE_FILENAME

    @property
    def photos_dir(self) -> Path:
        """Animal photos live beside the database, so DATA_DIR stays the one
        folder a deployment has to keep."""
        return self.data_dir / PHOTOS_DIRNAME


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
        stripe_secret_key=os.environ.get("STRIPE_SECRET_KEY") or None,
        stripe_webhook_secret=os.environ.get("STRIPE_WEBHOOK_SECRET") or None,
        public_base_url=_read_public_base_url(),
        cliq_alias=_read_optional("CLIQ_ALIAS"),
        bank_name=_read_optional("BANK_NAME"),
        bank_iban=_read_optional("BANK_IBAN"),
        bank_account_name=_read_optional("BANK_ACCOUNT_NAME"),
    )


def _read_optional(name: str) -> str | None:
    value = os.environ.get(name, "").strip()
    return value or None


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
    parts = urlsplit(candidate)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or "@" in parts.netloc
        or parts.path
        or parts.query
        or parts.fragment
    ):
        logger.warning("PUBLIC_BASE_URL=%r is not a plain http(s) origin; payments disabled", raw)
        return None
    return candidate


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

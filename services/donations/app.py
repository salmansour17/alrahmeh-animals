"""Entry point of the donations service: the append-only donation ledger, card
payments through Stripe, and the impact figures.

Start with:  python app.py   (development: applies migrations, then serves)

In a container the migrations run first, once, as their own step
(python migrate.py), then gunicorn starts the web server.

The service answers JSON only. It is the one service that calls another: it
asks the animals service whether an earmarked animal exists (ADR-6), through
HttpAnimalDirectory, wired in below.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from config import Config, load_config
from cors import enable_cors
from db import Database
from donations.animals_client import HttpAnimalDirectory, HttpAnimalNames
from donations.models import OfflineMethods
from donations.name_cache import CachedAnimalNames
from donations.payments import StripeGateway
from donations.repository import SqlDonationRepository
from donations.routes import create_donations_blueprint
from donations.service import AnimalDirectory, AnimalNames, DonationService, PaymentGateway
from hardening import PUBLIC_FORM, Hardening, install_hardening, request_context
from security import require_admin
from security_events import SecurityEvents

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Jordan has kept UTC+3 all year since abolishing daylight saving in 2022, so a
# fixed offset is exact, and avoids zoneinfo, which on Windows needs the extra
# tzdata package to know about Asia/Amman.
AMMAN = timezone(timedelta(hours=3), "Asia/Amman")

# Largest request body accepted. A Stripe webhook is a few kilobytes and a
# donation form far less; anything bigger is refused with 413 before parsing.
MAX_REQUEST_BYTES = 64 * 1024

# The largest BIGINT, the type of every id column; a larger id in a URL answers
# 404 instead of a driver error surfacing as a 500.
MAX_ID = 2**63 - 1

STRIPE_TEST_KEY_PREFIX = "sk_test_"
STRIPE_LIVE_KEY_PREFIX = "sk_live_"
# Where Stripe sends the donor afterwards: pages of the website (ui/), which
# only say thank you or offer to try again. Neither writes to the ledger.
CHECKOUT_SUCCESS_PATH = "/donate/thanks"
CHECKOUT_CANCEL_PATH = "/donate"


def amman_today() -> date:
    """The date in Jordan, whatever time zone the server runs in. A donation
    recorded at 01:00 in Amman is dated that day, not the UTC day before."""
    return datetime.now(AMMAN).date()


class IdConverter(IntegerConverter):
    """Flask's <int:...> converter, capped at the largest id the database stores."""

    def __init__(self, url_map, *args, **kwargs) -> None:
        kwargs.setdefault("max", MAX_ID)
        super().__init__(url_map, *args, **kwargs)


# Endpoints with a rate limit, by Flask endpoint name (hardening.py). Only
# the public form here: starting a card donation. Staff authentication has its own
# limit in security.py; /health is never limited, because the platform and
# the website's cold-start screen poll it.
RATE_LIMITED = {"donations.start_checkout": PUBLIC_FORM}


def create_app(
    config: Config | None = None,
    animals: AnimalDirectory | None = None,
    database: Database | None = None,
    animal_names: AnimalNames | None = None,
) -> Flask:
    """Build the service.

    Taking Config as an argument rather than reading the environment here is
    what lets tests build an app against their own database without mutating
    os.environ. `animals` lets a test hand in a stand-in for the animals
    service, and `animal_names` one for the names on the staff list; left
    out, the real HTTP adapters are used. Building the app touches
    no database: migrations run before it, once.
    """
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.url_map.converters["int"] = IdConverter

    # The composition root: concrete classes are chosen here and nowhere else.
    # The donation service only knows the AnimalDirectory Protocol, so moving
    # from an in-process adapter (Assignment 1) to an HTTP one was a change to
    # this one line.
    database = database or Database.from_url(config.database_url, appname=config.service)
    app.config["DATABASE"] = database
    # Security events (security_events.py): one JSON line each, from a
    # fixed list of fields. The donation rules emit two of them.
    events = SecurityEvents(config.service, context=request_context)

    donation_service = DonationService(
        SqlDonationRepository(database),
        animals=animals or HttpAnimalDirectory(config.animals_url, config.animals_timeout_s),
        today=amman_today,
        gateway=_payment_gateway(config),
        events=events,
        # The staff list's names: the same animals service, a separate client,
        # and a cache in front of it. The earmark check above never sees it.
        names=animal_names
        or CachedAnimalNames(
            HttpAnimalNames(config.animals_url, config.animals_timeout_s),
            ttl_s=config.animal_names_ttl_s,
            max_entries=config.animal_names_cache_size,
        ),
    )
    offline = OfflineMethods(
        cliq_alias=config.cliq_alias,
        bank_name=config.bank_name,
        bank_iban=config.bank_iban,
        bank_account_name=config.bank_account_name,
    )
    app.register_blueprint(create_donations_blueprint(donation_service, offline))

    app.register_error_handler(HTTPException, _json_http_error)
    _register_meta_routes(app)
    install_hardening(app, Hardening(config.hardening, events), RATE_LIMITED)
    _share_one_connection_per_request(app, database)
    enable_cors(app, config.cors_origins)
    return app


def _payment_gateway(config: Config) -> PaymentGateway | None:
    """Choose the card payment provider, or None to switch card donations off.

    Every "off" reason is logged once, here, by name, and never with any part
    of a key. The service still boots either way: a payment misconfiguration
    must not take the impact figures and offline donations down with it.
    """
    key, webhook_secret = config.stripe_secret_key, config.stripe_webhook_secret
    if key and key.startswith(STRIPE_LIVE_KEY_PREFIX):
        logger.error("Card donations disabled: live key refused, this build is test mode only")
        return None
    if not key or not webhook_secret:
        logger.warning("Card donations disabled: STRIPE_SECRET_KEY or STRIPE_WEBHOOK_SECRET not set")
        return None
    if not key.startswith(STRIPE_TEST_KEY_PREFIX):
        logger.error("Card donations disabled: STRIPE_SECRET_KEY is not a test-mode secret key")
        return None
    if config.public_base_url is None:
        logger.error("Card donations disabled: PUBLIC_BASE_URL is invalid")
        return None
    return StripeGateway(
        secret_key=key,
        webhook_secret=webhook_secret,
        success_url=config.public_base_url + CHECKOUT_SUCCESS_PATH,
        cancel_url=config.public_base_url + CHECKOUT_CANCEL_PATH,
        local_timezone=AMMAN,
    )


def _json_http_error(error: HTTPException):
    """Answer Flask's own errors in JSON instead of an HTML page. Unhandled
    exceptions still become a bare 500 with no traceback, because debug is off
    unless FLASK_DEBUG=1."""
    name = error.name.lower().replace(" ", "_")
    if error.code == 413:
        detail = f"Too large: a request can be at most {MAX_REQUEST_BYTES // 1024} KB."
        return jsonify(error=name, detail=detail), 413
    return jsonify(error=name), error.code


def _register_meta_routes(app: Flask) -> None:
    """Endpoints that describe the service rather than its domain."""
    database: Database = app.config["DATABASE"]

    @app.get("/health")
    def health():
        """200 when this service can read and write its own database, 503 when
        it cannot. It reflects this service only: it does not call the animals service, so one service being
        down never marks another unhealthy. Public, so it says nothing about
        why: the reason goes to the log, by error number only.

        The platform's probes and the deploy pipeline call this. `version` is
        the git commit the image was built from (GIT_SHA), "dev" otherwise.
        """
        version = app.config["APP_CONFIG"].version
        try:
            database.check_read_write()
        except Exception as error:  # noqa: BLE001 (any failure means not healthy)
            number = error.args[0] if error.args and isinstance(error.args[0], int) else type(error).__name__
            logger.warning("Health check failed: database not readable and writable (%s)", number)
            return jsonify(status="error", db="error", version=version), 503
        return jsonify(status="ok", db="ok", version=version)

    @app.get("/api/meta/schema")
    @require_admin
    def schema():
        """Tables currently present. Staff-only."""
        return jsonify(tables=database.table_names())


def _share_one_connection_per_request(app: Flask, database: Database) -> None:
    """Each request opens at most one database connection, shared by all its
    units of work and closed when the request ends, error or not (db.py,
    Database.begin_request, says why). teardown_request runs even when the
    view raised, so no connection outlives its request."""

    @app.before_request
    def _begin() -> None:
        g.database_request = database.begin_request()

    @app.teardown_request
    def _end(_error: BaseException | None) -> None:
        token = g.pop("database_request", None)
        if token is not None:
            database.end_request(token)


def main() -> None:
    from migrate import apply_migrations

    config = load_config()
    database = Database.from_url(config.database_url, appname=config.service)
    apply_migrations(database)
    app = create_app(config, database=database)
    logger.info("Donations service on http://%s:%d, database %s", config.host, config.port, database.name)
    logger.info("Animals service expected at %s", config.animals_url)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()

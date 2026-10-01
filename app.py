"""Entry point for the Al-Rahmeh Association for Animals application.

Start with:  python app.py

One Flask process serves both feature domains as JSON endpoints and, once the
frontend is built, the compiled React bundle from static/dist. There is no
separate web server, worker or build step at runtime.
"""

from __future__ import annotations

import logging
import mimetypes
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import Flask, abort, jsonify, send_from_directory
from werkzeug.exceptions import HTTPException, NotFound

from config import Config, load_config
from db.connection import Database
from domains.animals.repository import SqliteAnimalRepository
from domains.animals.routes import create_animals_blueprint
from domains.animals.service import AnimalNotFound, AnimalService
from domains.donations.repository import SqliteDonationRepository
from domains.donations.payments import StripeGateway
from domains.donations.routes import create_donations_blueprint
from domains.donations.service import DonationService, PaymentGateway
from security import require_admin

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Jordan has kept UTC+3 all year since abolishing daylight saving in 2022, so a
# fixed offset is exact, and avoids zoneinfo, which on Windows needs the extra
# tzdata package to know about Asia/Amman.
AMMAN = timezone(timedelta(hours=3), "Asia/Amman")

# Largest request body accepted anywhere. A Stripe webhook is a few kilobytes and
# a donation form far less; anything bigger is refused with 413 before parsing.
MAX_REQUEST_BYTES = 64 * 1024

STRIPE_TEST_KEY_PREFIX = "sk_test_"
STRIPE_LIVE_KEY_PREFIX = "sk_live_"
# Where Stripe sends the donor afterwards: frontend pages, which only say thank
# you or offer to try again. Neither writes to the ledger.
CHECKOUT_SUCCESS_PATH = "/donate/thanks"
CHECKOUT_CANCEL_PATH = "/donate"

# The compiled React app. Committed to the repository, so a clone plus
# `pip install` plus `python app.py` serves the whole site without Node.
FRONTEND_DIST = Path(__file__).resolve().parent / "static" / "dist"
API_PREFIX = "api/"
# Python's type table does not know .woff2 on every platform (Windows among
# them), and the bundled font would otherwise go out as a generic download.
mimetypes.add_type("font/woff2", ".woff2")


def amman_today() -> date:
    """The date in Jordan, whatever time zone the server runs in. A donation
    recorded at 01:00 in Amman is dated that day, not the UTC day before."""
    return datetime.now(AMMAN).date()


class AnimalDirectoryAdapter:
    """Adapter: lets the donations domain ask "does this animal exist?"
    through its own one-method AnimalDirectory interface, answered by the animal
    domain's AnimalService.

    It lives here, at the composition root, because this is the only module
    allowed to import both domains. Neither package knows the other exists.
    """

    def __init__(self, animals: AnimalService) -> None:
        self._animals = animals

    def exists(self, animal_id: int) -> bool:
        try:
            self._animals.get(animal_id)
        except AnimalNotFound:
            return False
        return True


def create_app(config: Config | None = None) -> Flask:
    """Build the application.

    Taking Config as an argument rather than reading the environment here is
    what lets tests construct an app against a temporary data directory
    without mutating os.environ.
    """
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES

    config.data_dir.mkdir(parents=True, exist_ok=True)

    # The composition root: the Database is built once here and handed to
    # whatever needs it, so no module below this line decides where the SQLite
    # file lives.
    database = Database(config.database_path)
    database.initialise()
    app.config["DATABASE"] = database

    # Each domain gets its concrete repository here and nowhere else. Each
    # service only knows the Protocols it declares, so swapping SQLite, or
    # replacing the adapter with an HTTP call once the domains are separate
    # services, would be a change to these lines alone.
    animal_service = AnimalService(SqliteAnimalRepository(database), today=amman_today)
    app.register_blueprint(create_animals_blueprint(animal_service))

    donation_service = DonationService(
        SqliteDonationRepository(database),
        animals=AnimalDirectoryAdapter(animal_service),
        today=amman_today,
        gateway=_payment_gateway(config),
    )
    app.register_blueprint(create_donations_blueprint(donation_service))

    app.register_error_handler(HTTPException, _json_http_error)
    _register_meta_routes(app)
    # Last, so every /api route above is matched before the catch-all below.
    _register_frontend_routes(app, FRONTEND_DIST)
    return app


def _payment_gateway(config: Config) -> PaymentGateway | None:
    """Choose the card payment provider, or None to switch card donations off.

    Every "off" reason is logged once, here, by name, and never with any part
    of a key. The app still boots either way: a payment misconfiguration must
    not take the animal pages and impact counters down with it.
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
    """Answer Flask's own errors (unknown URL, wrong method) in JSON, like the
    domain errors, instead of an HTML page. Unhandled exceptions still become a
    bare 500 with no traceback, because debug is off unless FLASK_DEBUG=1."""
    return jsonify(error=error.name.lower().replace(" ", "_")), error.code


def _register_meta_routes(app: Flask) -> None:
    """Endpoints that describe the service rather than either feature domain."""
    config: Config = app.config["APP_CONFIG"]
    database: Database = app.config["DATABASE"]

    @app.get("/api/health")
    def health():
        """Liveness probe. Deliberately does not query the database, so it still
        answers when storage is broken."""
        return jsonify(status="ok", database_path=str(config.database_path))

    @app.get("/api/meta/schema")
    @require_admin
    def schema():
        """Tables currently present: a quick way to confirm the schema applied
        itself on startup.

        Staff-only. It describes the internal storage layout, which is of no use
        to a visitor and of some use to someone probing the service.
        """
        return jsonify(tables=database.table_names())


def _register_frontend_routes(app: Flask, dist: Path) -> None:
    """Serve the built React app, and hand every other non-API path to it.

    React Router owns URLs like /animals/3 in the browser. When one is opened
    directly or reloaded, the request reaches Flask, which has no such route,
    so any path that is not a real file in the build gets index.html and React
    shows the right page. /api paths are never handed over: an unknown API URL
    must answer a JSON 404, not a web page.
    """

    @app.get("/", defaults={"path": ""})
    @app.get("/<path:path>")
    def frontend(path: str):
        if path.startswith(API_PREFIX):
            abort(404)
        if not (dist / "index.html").is_file():
            return (
                "Al-Rahmeh Association for Animals - API is running.\n"
                "The React frontend has not been built into static/dist yet.\n",
                200,
                {"Content-Type": "text/plain; charset=utf-8"},
            )
        if path:
            # send_from_directory refuses anything that would resolve outside
            # dist (../app.py and the like), so the build folder is the only
            # thing this route can ever read.
            try:
                return send_from_directory(dist, path)
            except NotFound:
                pass
        return send_from_directory(dist, "index.html")


def main() -> None:
    config = load_config()
    app = create_app(config)
    logger.info("Serving on http://%s:%d", config.host, config.port)
    logger.info("SQLite file: %s", config.database_path)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()

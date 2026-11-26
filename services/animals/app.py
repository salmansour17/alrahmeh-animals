"""Entry point of the animals service: animal intake, the placement lifecycle,
adoption and foster requests, offline adoptions and photos.

Start with:  python app.py   (development: applies migrations, adds sample
animals if the database has none, then serves)

In a container the same steps run separately, so they happen once before the
web server starts its workers: python migrate.py, python sample_animals.py,
then gunicorn.

The service answers JSON only. The website is a separate static build in ui/
that calls this service and the others over HTTP (ADR-6). This service calls no
other service, so it can start, run and be tested on its own.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from animals.photos import MAX_PHOTO_BYTES, prepare_photo
from animals.repository import SqlAnimalRepository, SqlPhotoStore, SqlPlacementRepository
from animals.routes import create_animals_blueprint, create_requests_blueprint
from animals.service import AnimalService, PhotoService, PlacementService
from config import Config, load_config
from cors import enable_cors
from db import Database
from security import require_admin

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Jordan has kept UTC+3 all year since abolishing daylight saving in 2022, so a
# fixed offset is exact, and avoids zoneinfo, which on Windows needs the extra
# tzdata package to know about Asia/Amman.
AMMAN = timezone(timedelta(hours=3), "Asia/Amman")

# Largest request body accepted, except photo uploads, which raise their own
# limit in routes.py. Anything bigger is refused with 413 before parsing.
MAX_REQUEST_BYTES = 64 * 1024

# The largest BIGINT, the type of every id column. A larger id in a URL could
# never match a row, and the driver would fail to send it, which would surface
# as a 500, so such a URL simply does not match a route and answers 404.
MAX_ID = 2**63 - 1


def amman_today() -> date:
    """The date in Jordan, whatever time zone the server runs in."""
    return datetime.now(AMMAN).date()


class IdConverter(IntegerConverter):
    """Flask's <int:...> converter, capped at the largest id the database stores."""

    def __init__(self, url_map, *args, **kwargs) -> None:
        kwargs.setdefault("max", MAX_ID)
        super().__init__(url_map, *args, **kwargs)


def create_app(config: Config | None = None, database: Database | None = None) -> Flask:
    """Build the service.

    Taking Config as an argument rather than reading the environment here is
    what lets tests build an app against their own database without mutating
    os.environ. Building the app touches no database: migrations and sample
    data run before it, once, not in every web server worker.
    """
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    # Before any blueprint is registered, so every <int:...> uses the bound.
    app.url_map.converters["int"] = IdConverter

    # The composition root: concrete classes are chosen here and nowhere else.
    database = database or Database.from_url(config.database_url, appname=config.service)
    app.config["DATABASE"] = database

    animal_service = AnimalService(SqlAnimalRepository(database), today=amman_today)
    placement_service = PlacementService(SqlPlacementRepository(database), animal_service)
    photo_service = PhotoService(animal_service, SqlPhotoStore(database), prepare=prepare_photo)
    app.register_blueprint(create_animals_blueprint(animal_service, placement_service, photo_service))
    app.register_blueprint(create_requests_blueprint(placement_service))

    app.register_error_handler(HTTPException, _json_http_error)
    _register_meta_routes(app)
    _share_one_connection_per_request(app, database)
    enable_cors(app, config.cors_origins)
    return app


def _json_http_error(error: HTTPException):
    """Answer Flask's own errors (unknown URL, wrong method) in JSON, like the
    domain errors, instead of an HTML page. Unhandled exceptions still become a
    bare 500 with no traceback, because debug is off unless FLASK_DEBUG=1."""
    name = error.name.lower().replace(" ", "_")
    if error.code == 413:
        # Said in words, because the staff portal shows `detail` to the user.
        photo_mb = MAX_PHOTO_BYTES // (1024 * 1024)
        other_kb = MAX_REQUEST_BYTES // 1024
        detail = f"Too large: a photo can be at most {photo_mb} MB, and any other request {other_kb} KB."
        return jsonify(error=name, detail=detail), 413
    return jsonify(error=name), error.code


def _register_meta_routes(app: Flask) -> None:
    """Endpoints that describe the service rather than its domain."""
    database: Database = app.config["DATABASE"]

    @app.get("/health")
    def health():
        """200 when this service can read and write its own database, 503 when
        it cannot. It reflects this service only, so one service being
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
        """Tables currently present, to confirm the schema applied on startup.
        Staff-only: it describes the internal storage layout."""
        return jsonify(tables=database.table_names())


def main() -> None:
    """Development start: the same steps as the container, in one process."""
    from migrate import apply_migrations
    from sample_animals import add_sample_animals

    config = load_config()
    database = Database.from_url(config.database_url, appname=config.service)
    apply_migrations(database)
    if config.sample_animals:
        add_sample_animals(AnimalService(SqlAnimalRepository(database), today=amman_today))
    app = create_app(config, database)
    logger.info("Animals service on http://%s:%d, database %s", config.host, config.port, database.name)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()


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

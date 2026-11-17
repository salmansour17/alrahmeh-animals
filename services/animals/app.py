"""Entry point of the animals service: animal intake, the placement lifecycle,
adoption and foster requests, offline adoptions and photos.

Start with:  python app.py

The service answers JSON only. The website is a separate static build in ui/
that calls this service and the others over HTTP (ADR-6). This service calls no
other service, so it can start, run and be tested on its own.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from animals.photos import MAX_PHOTO_BYTES, FileSystemPhotoStore, prepare_photo
from animals.repository import SqliteAnimalRepository, SqlitePlacementRepository
from animals.routes import create_animals_blueprint, create_requests_blueprint
from animals.service import AnimalService, PhotoService, PlacementService
from config import Config, load_config
from db import Database
from sample_animals import add_sample_animals
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

# The largest integer SQLite can store. A larger id in a URL could never match a
# row, and handing it to sqlite3 raises OverflowError, which would surface as a
# 500, so such a URL simply does not match a route and answers 404.
SQLITE_MAX_INTEGER = 2**63 - 1


def amman_today() -> date:
    """The date in Jordan, whatever time zone the server runs in."""
    return datetime.now(AMMAN).date()


class SqliteIdConverter(IntegerConverter):
    """Flask's <int:...> converter, capped at the largest value SQLite stores."""

    def __init__(self, url_map, *args, **kwargs) -> None:
        kwargs.setdefault("max", SQLITE_MAX_INTEGER)
        super().__init__(url_map, *args, **kwargs)


def create_app(config: Config | None = None) -> Flask:
    """Build the service.

    Taking Config as an argument rather than reading the environment here is
    what lets tests build an app against a temporary data directory without
    mutating os.environ.
    """
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    # Before any blueprint is registered, so every <int:...> uses the bound.
    app.url_map.converters["int"] = SqliteIdConverter

    config.data_dir.mkdir(parents=True, exist_ok=True)

    # The composition root: concrete classes are chosen here and nowhere else.
    database = Database(config.database_path)
    database.initialise()
    app.config["DATABASE"] = database

    animal_service = AnimalService(SqliteAnimalRepository(database), today=amman_today)
    placement_service = PlacementService(SqlitePlacementRepository(database), animal_service)
    if config.sample_animals:
        add_sample_animals(animal_service)
    photo_service = PhotoService(
        animal_service, FileSystemPhotoStore(config.photos_dir), prepare=prepare_photo
    )
    app.register_blueprint(create_animals_blueprint(animal_service, placement_service, photo_service))
    app.register_blueprint(create_requests_blueprint(placement_service))

    app.register_error_handler(HTTPException, _json_http_error)
    _register_meta_routes(app)
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

    @app.get("/api/health")
    def health():
        """Liveness probe. Public, so it reveals nothing about the host."""
        return jsonify(status="ok")

    @app.get("/api/meta/schema")
    @require_admin
    def schema():
        """Tables currently present, to confirm the schema applied on startup.
        Staff-only: it describes the internal storage layout."""
        return jsonify(tables=database.table_names())


def main() -> None:
    config = load_config()
    app = create_app(config)
    logger.info("Animals service on http://%s:%d", config.host, config.port)
    logger.info("SQLite file: %s", config.database_path)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()

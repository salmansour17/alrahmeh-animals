"""Entry point of the enquiries service: contact and volunteer messages from
the public, kept for staff.

Start with:  python app.py

The service answers JSON only. It calls no other service and no other service
calls it (ADR-6); the website in ui/ calls it directly.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from config import Config, load_config
from db import Database
from enquiries.repository import SqliteEnquiryRepository
from enquiries.routes import create_enquiries_blueprint
from enquiries.service import EnquiryService
from security import require_admin

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Largest request body accepted. A contact message is far smaller; anything
# bigger is refused with 413 before parsing.
MAX_REQUEST_BYTES = 64 * 1024

# The largest integer SQLite can store; a larger id in a URL answers 404
# instead of an OverflowError surfacing as a 500.
SQLITE_MAX_INTEGER = 2**63 - 1


class SqliteIdConverter(IntegerConverter):
    """Flask's <int:...> converter, capped at the largest value SQLite stores."""

    def __init__(self, url_map, *args, **kwargs) -> None:
        kwargs.setdefault("max", SQLITE_MAX_INTEGER)
        super().__init__(url_map, *args, **kwargs)


def create_app(config: Config | None = None) -> Flask:
    """Build the service from a Config, so tests can point it at a temporary
    directory without touching os.environ."""
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.url_map.converters["int"] = SqliteIdConverter

    config.data_dir.mkdir(parents=True, exist_ok=True)

    # The composition root: concrete classes are chosen here and nowhere else.
    database = Database(config.database_path)
    database.initialise()
    app.config["DATABASE"] = database

    app.register_blueprint(
        create_enquiries_blueprint(EnquiryService(SqliteEnquiryRepository(database)))
    )

    app.register_error_handler(HTTPException, _json_http_error)
    _register_meta_routes(app)
    return app


def _json_http_error(error: HTTPException):
    """Answer Flask's own errors in JSON instead of an HTML page."""
    name = error.name.lower().replace(" ", "_")
    if error.code == 413:
        detail = f"Too large: a request can be at most {MAX_REQUEST_BYTES // 1024} KB."
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
        """Tables currently present. Staff-only."""
        return jsonify(tables=database.table_names())


def main() -> None:
    config = load_config()
    app = create_app(config)
    logger.info("Enquiries service on http://%s:%d", config.host, config.port)
    logger.info("SQLite file: %s", config.database_path)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()

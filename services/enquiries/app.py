"""Entry point of the enquiries service: contact and volunteer messages from
the public, kept for staff.

Start with:  python app.py   (development: applies migrations, then serves)

In a container the migrations run first, once, as their own step
(python migrate.py), then gunicorn starts the web server.

The service answers JSON only. It calls no other service and no other service
calls it (ADR-6); the website in ui/ calls it directly.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException
from werkzeug.routing import IntegerConverter

from config import Config, load_config
from cors import enable_cors
from db import Database
from enquiries.repository import SqlEnquiryRepository
from enquiries.routes import create_enquiries_blueprint
from enquiries.service import EnquiryService
from security import require_admin

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# Largest request body accepted. A contact message is far smaller; anything
# bigger is refused with 413 before parsing.
MAX_REQUEST_BYTES = 64 * 1024

# The largest BIGINT, the type of every id column; a larger id in a URL answers
# 404 instead of a driver error surfacing as a 500.
MAX_ID = 2**63 - 1


class IdConverter(IntegerConverter):
    """Flask's <int:...> converter, capped at the largest id the database stores."""

    def __init__(self, url_map, *args, **kwargs) -> None:
        kwargs.setdefault("max", MAX_ID)
        super().__init__(url_map, *args, **kwargs)


def create_app(config: Config | None = None, database: Database | None = None) -> Flask:
    """Build the service from a Config (and optionally a Database), so tests can
    point it at their own database without touching os.environ. Building the
    app touches no database: migrations run before it, once."""
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config
    app.config["MAX_CONTENT_LENGTH"] = MAX_REQUEST_BYTES
    app.url_map.converters["int"] = IdConverter

    # The composition root: concrete classes are chosen here and nowhere else.
    database = database or Database.from_url(config.database_url, appname=config.service)
    app.config["DATABASE"] = database

    app.register_blueprint(
        create_enquiries_blueprint(EnquiryService(SqlEnquiryRepository(database)))
    )

    app.register_error_handler(HTTPException, _json_http_error)
    _register_meta_routes(app)
    enable_cors(app, config.cors_origins)
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
        """Tables currently present. Staff-only."""
        return jsonify(tables=database.table_names())


def main() -> None:
    from migrate import apply_migrations

    config = load_config()
    database = Database.from_url(config.database_url, appname=config.service)
    apply_migrations(database)
    app = create_app(config, database)
    logger.info("Enquiries service on http://%s:%d, database %s", config.host, config.port, database.name)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()

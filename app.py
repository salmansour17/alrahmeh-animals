"""Entry point for the Al-Rahmeh Association for Animals application.

Start with:  python app.py

One Flask process serves both feature domains as JSON endpoints and, once the
frontend is built, the compiled React bundle from static/dist. There is no
separate web server, worker or build step at runtime.
"""

from __future__ import annotations

import logging

from flask import Flask, jsonify

from config import Config, load_config
from db.connection import Database
from security import require_admin

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> Flask:
    """Build the application.

    Taking Config as an argument rather than reading the environment here is
    what lets tests construct an app against a temporary data directory
    without mutating os.environ.
    """
    config = config or load_config()
    app = Flask(__name__, static_folder=None)
    app.config["APP_CONFIG"] = config

    config.data_dir.mkdir(parents=True, exist_ok=True)

    # The composition root: the Database is built once here and handed to
    # whatever needs it, so no module below this line decides where the SQLite
    # file lives.
    database = Database(config.database_path)
    database.initialise()
    app.config["DATABASE"] = database

    _register_meta_routes(app)
    return app


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

    @app.get("/")
    def index():
        return (
            "Al-Rahmeh Association for Animals - API is running.\n"
            "The React frontend has not been built into static/dist yet.\n",
            200,
            {"Content-Type": "text/plain; charset=utf-8"},
        )


def main() -> None:
    config = load_config()
    app = create_app(config)
    logger.info("Serving on http://%s:%d", config.host, config.port)
    logger.info("SQLite file: %s", config.database_path)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()

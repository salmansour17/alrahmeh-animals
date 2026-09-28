"""SQLite connection handling and schema initialisation.

This module is the only place in the project that imports `sqlite3`. Domain
repositories receive a `Database` and ask it for connections, so neither domain
knows where the file lives or how it is configured. That is the dependency
inversion the project brief calls for: the domains depend on this small
interface, not on the driver.
"""

from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class Database:
    """Owns one SQLite file and hands out configured connections."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def connect(self) -> sqlite3.Connection:
        """Open a connection with the settings every caller needs.

        A new connection per unit of work rather than one shared connection:
        SQLite connections are not safe to use from multiple threads, and Flask
        serves requests on more than one thread.
        """
        connection = sqlite3.connect(self._path)
        # Return mapping-style rows so repositories can read columns by name
        # instead of by position, which keeps them readable as the schema grows.
        connection.row_factory = sqlite3.Row
        # SQLite disables foreign key enforcement per connection by default, so
        # medical_records and placement_requests would not actually cascade
        # without this.
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        """Run a block inside one transaction, then commit or roll back.

        Committing on the way out and rolling back on an exception means a
        half-applied write cannot survive an error, and callers never have to
        remember to commit.
        """
        connection = self.connect()
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialise(self) -> None:
        """Apply schema.sql. Safe to run on every startup.

        Every statement in the schema is CREATE ... IF NOT EXISTS, so this is
        idempotent: an empty data directory and an existing database take the
        same path. That is what removes the need for a migration step at boot.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        with self.unit_of_work() as connection:
            connection.executescript(schema)
        logger.info("Schema applied to %s", self._path)

    def table_names(self) -> list[str]:
        """Tables currently present. Used by the health endpoint and by tests."""
        with self.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ).fetchall()
        return [row["name"] for row in rows]

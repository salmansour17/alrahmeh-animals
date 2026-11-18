"""Versioned database migrations for this service, and the runner that applies
them.

    python migrate.py

The schema is defined by the numbered files in migrations/ (001_init.sql,
002_..., ...). On every start, before the web server, this applies the ones the
database has not seen yet, in order, and records each in `schema_migrations`.
A second run applies nothing.

Rules the runner enforces:

- A file applied once is never applied again, and never edited: its SHA-256 is
  recorded, and if the file on disk no longer matches, the runner refuses to
  continue. A correction goes in a new file.
- Each file runs in one transaction with its own row in schema_migrations, so a
  failing migration leaves no trace and is tried again next start.
- An exclusive application lock means two copies starting at once cannot both
  apply the same file; the second waits, then finds nothing left to do.
- Nothing here drops or deletes. The runner only creates its own table if it is
  missing, and runs the files.

Inside a file, a line containing only GO separates batches, as in SQL Server's
own tools. SQL Server needs that for statements that must start a batch, such
as CREATE TRIGGER. A file with no GO line is a single batch.

Each service has its own copy of this file (ADR-6).
"""

from __future__ import annotations

import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from db import Connection, Database

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().with_name("migrations")
FILENAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
BATCH_SEPARATOR = re.compile(r"^\s*GO\s*;?\s*$", re.IGNORECASE | re.MULTILINE)
LOCK_TIMEOUT_MS = 120_000

CREATE_TRACKING_TABLE = """
IF OBJECT_ID(N'dbo.schema_migrations', N'U') IS NULL
    CREATE TABLE dbo.schema_migrations (
        version    INT           NOT NULL CONSTRAINT pk_schema_migrations PRIMARY KEY,
        filename   NVARCHAR(200) NOT NULL,
        sha256     CHAR(64)      NOT NULL,
        applied_at DATETIME2(0)  NOT NULL CONSTRAINT df_schema_migrations_applied_at DEFAULT SYSUTCDATETIME()
    );
"""


class MigrationError(RuntimeError):
    """The migrations on disk and in the database disagree, or one failed."""


@dataclass(frozen=True)
class Migration:
    version: int
    filename: str
    sql: str

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.sql.encode("utf-8")).hexdigest()

    def batches(self) -> list[str]:
        return [batch.strip() for batch in BATCH_SEPARATOR.split(self.sql) if batch.strip()]


def load_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """Every migration file, in version order. A file that does not follow
    NNN_name.sql, or two files with the same number, is an error rather than
    something to guess about."""
    migrations: dict[int, Migration] = {}
    for path in sorted(directory.glob("*.sql")):
        match = FILENAME.match(path.name)
        if not match:
            raise MigrationError(f"{path.name}: migration files are named NNN_lower_case_name.sql")
        version = int(match.group(1))
        if version in migrations:
            raise MigrationError(f"two migrations share number {version:03d}")
        migrations[version] = Migration(version, path.name, path.read_text(encoding="utf-8"))
    return [migrations[version] for version in sorted(migrations)]


def apply_migrations(database: Database, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply every migration the database has not recorded yet. Returns the
    filenames applied, which is empty on a second run."""
    migrations = load_migrations(directory)
    with database.unit_of_work() as connection:
        connection.execute(CREATE_TRACKING_TABLE)

    applied_now: list[str] = []
    for migration in migrations:
        with database.unit_of_work() as connection:
            # Held until this transaction ends. A second runner blocks here
            # instead of applying the same file at the same time.
            _lock(connection)
            recorded = _recorded(connection)
            if migration.version in recorded:
                _check_unchanged(migration, recorded[migration.version])
                continue
            for batch in migration.batches():
                connection.execute(batch)
            connection.execute(
                "INSERT INTO dbo.schema_migrations (version, filename, sha256) VALUES (%s, %s, %s)",
                (migration.version, migration.filename, migration.sha256),
            )
        logger.info("Applied migration %s to %s", migration.filename, database.name)
        applied_now.append(migration.filename)

    if not applied_now:
        logger.info("Database %s is up to date (%d migrations)", database.name, len(migrations))
    return applied_now


def _lock(connection: Connection) -> None:
    result = connection.execute(
        "DECLARE @result INT; "
        "EXEC @result = sp_getapplock @Resource = N'schema_migrations', @LockMode = N'Exclusive', "
        "@LockOwner = N'Transaction', @LockTimeout = %s; "
        "SELECT @result AS result",
        (LOCK_TIMEOUT_MS,),
    ).fetchone()
    if result["result"] < 0:
        raise MigrationError("another copy of this service is still applying migrations")


def _recorded(connection: Connection) -> dict[int, tuple[str, str]]:
    rows = connection.execute("SELECT version, filename, sha256 FROM dbo.schema_migrations").fetchall()
    return {row["version"]: (row["filename"], row["sha256"]) for row in rows}


def _check_unchanged(migration: Migration, recorded: tuple[str, str]) -> None:
    filename, sha256 = recorded
    if filename != migration.filename or sha256 != migration.sha256:
        raise MigrationError(
            f"{migration.filename} differs from the version {migration.version:03d} already applied "
            f"({filename}). Applied migrations are never edited; put the change in a new file."
        )


def main() -> int:
    """Run from the container's start command, before the web server. A
    non-zero exit stops the start, so the service never runs on a schema it
    does not expect."""
    from config import load_config

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    config = load_config()
    try:
        apply_migrations(Database.from_url(config.database_url, appname=f"{config.service}-migrate"))
    except Exception as error:  # noqa: BLE001 (report any failure and stop)
        logger.error("Migrations failed, not starting: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

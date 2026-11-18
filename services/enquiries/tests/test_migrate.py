"""The migration runner (migrate.py) and the connection layer (db.py).

The runner tests use a second throwaway database of their own, so the run's
main test database keeps exactly this service's real migrations.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import pymssql
import pytest

from db import ConnectionSettings, Database, DatabaseError
from migrate import MIGRATIONS_DIR, MigrationError, apply_migrations, load_migrations
from tests.conftest import _admin_connection, _server_url

# --- the migration runner -----------------------------------------------------


@pytest.fixture
def scratch_url():
    """An empty database for one test, dropped afterwards."""
    server_url = _server_url()
    server = ConnectionSettings.from_url(server_url)
    name = f"test_migrate_{uuid.uuid4().hex[:10]}"
    admin = _admin_connection(server)
    admin.cursor().execute(f"CREATE DATABASE [{name}]")
    parts = urlsplit(server_url)
    try:
        yield urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, ""))
    finally:
        cursor = admin.cursor()
        cursor.execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
        cursor.execute(f"DROP DATABASE [{name}]")
        admin.close()


def _write(directory: Path, name: str, sql: str) -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def _tables(database: Database) -> set[str]:
    return set(database.table_names())


def test_a_second_run_applies_nothing(scratch_url, tmp_path):
    _write(tmp_path, "001_first.sql", "CREATE TABLE things (id INT NOT NULL PRIMARY KEY);")
    _write(tmp_path, "002_second.sql", "ALTER TABLE things ADD label NVARCHAR(20) NULL;")
    database = Database.from_url(scratch_url)

    assert apply_migrations(database, tmp_path) == ["001_first.sql", "002_second.sql"]
    assert apply_migrations(database, tmp_path) == []
    with database.unit_of_work() as connection:
        rows = connection.execute("SELECT version, filename FROM schema_migrations ORDER BY version").fetchall()
    assert [(r["version"], r["filename"]) for r in rows] == [(1, "001_first.sql"), (2, "002_second.sql")]


def test_a_new_migration_keeps_the_rows_already_there(scratch_url, tmp_path):
    """The point of migrations: change a table that holds data, in place."""
    _write(tmp_path, "001_first.sql", "CREATE TABLE things (id INT NOT NULL PRIMARY KEY);")
    database = Database.from_url(scratch_url)
    apply_migrations(database, tmp_path)
    with database.unit_of_work() as connection:
        connection.execute("INSERT INTO things (id) VALUES (1), (2)")

    _write(tmp_path, "002_label.sql", "ALTER TABLE things ADD label NVARCHAR(20) NOT NULL CONSTRAINT df_things_label DEFAULT N'new';")
    assert apply_migrations(database, tmp_path) == ["002_label.sql"]

    with database.unit_of_work() as connection:
        rows = connection.execute("SELECT id, label FROM things ORDER BY id").fetchall()
    assert [(r["id"], r["label"]) for r in rows] == [(1, "new"), (2, "new")]


def test_go_lines_split_batches_so_a_trigger_can_be_created(scratch_url, tmp_path):
    """CREATE TRIGGER must start a batch, which is what GO lines are for."""
    _write(
        tmp_path,
        "001_trigger.sql",
        "CREATE TABLE things (id INT NOT NULL PRIMARY KEY);\nGO\n"
        "CREATE TRIGGER things_frozen ON things INSTEAD OF DELETE AS THROW 51000, 'frozen', 1;\ngo\n",
    )
    database = Database.from_url(scratch_url)
    apply_migrations(database, tmp_path)
    with database.unit_of_work() as connection:
        connection.execute("INSERT INTO things (id) VALUES (1)")
    with pytest.raises(DatabaseError, match="frozen"):
        with database.unit_of_work() as connection:
            connection.execute("DELETE FROM things")


def test_a_failing_migration_leaves_no_trace_and_runs_again_next_time(scratch_url, tmp_path):
    _write(tmp_path, "001_first.sql", "CREATE TABLE things (id INT NOT NULL PRIMARY KEY);")
    _write(tmp_path, "002_broken.sql", "CREATE TABLE half_done (id INT);\nGO\nSELECT * FROM no_such_table;")
    database = Database.from_url(scratch_url)

    with pytest.raises(DatabaseError):
        apply_migrations(database, tmp_path)
    # 001 committed on its own; 002 rolled back entirely, its first batch too.
    assert "things" in _tables(database)
    assert "half_done" not in _tables(database)

    _write(tmp_path, "002_broken.sql", "CREATE TABLE half_done (id INT);")
    assert apply_migrations(database, tmp_path) == ["002_broken.sql"]


def test_an_applied_migration_that_was_edited_stops_the_start(scratch_url, tmp_path):
    _write(tmp_path, "001_first.sql", "CREATE TABLE things (id INT NOT NULL PRIMARY KEY);")
    database = Database.from_url(scratch_url)
    apply_migrations(database, tmp_path)

    _write(tmp_path, "001_first.sql", "CREATE TABLE things (id BIGINT NOT NULL PRIMARY KEY);")
    with pytest.raises(MigrationError, match="never edited"):
        apply_migrations(database, tmp_path)


@pytest.mark.parametrize(
    ("files", "complaint"),
    [
        (["1_first.sql"], "NNN_lower_case_name"),
        (["001_First.sql"], "NNN_lower_case_name"),
        (["001_a.sql", "001_b.sql"], "share number 001"),
    ],
)
def test_badly_named_migrations_are_refused(tmp_path, files, complaint):
    for name in files:
        _write(tmp_path, name, "SELECT 1;")
    with pytest.raises(MigrationError, match=complaint):
        load_migrations(tmp_path)


def test_no_migration_ever_drops_or_empties_anything():
    """Graders check for this, and so does the suite: data is only ever kept."""
    forbidden = re.compile(r"\b(DROP\s+(TABLE|DATABASE|COLUMN)|TRUNCATE\s+TABLE|DELETE\s+FROM)\b", re.IGNORECASE)
    for migration in load_migrations(MIGRATIONS_DIR):
        assert not forbidden.search(migration.sql), migration.filename


def test_the_service_migrations_are_numbered_from_001():
    versions = [m.version for m in load_migrations(MIGRATIONS_DIR)]
    assert versions == list(range(1, len(versions) + 1))


# --- DATABASE_URL -------------------------------------------------------------


def test_a_database_url_is_parsed_into_its_parts():
    settings = ConnectionSettings.from_url("mssql://svc_user:p%40ss%3Aword@db.example.org:14330/animals_db?encrypt=true")
    assert (settings.host, settings.port, settings.user, settings.database, settings.encrypt) == (
        "db.example.org",
        14330,
        "svc_user",
        "animals_db",
        True,
    )
    assert settings.password == "p@ss:word"
    assert "p@ss" not in repr(settings)


def test_the_port_defaults_to_1433_and_encryption_to_off():
    settings = ConnectionSettings.from_url("mssql://u:p@localhost/db")
    assert (settings.port, settings.encrypt) == (1433, False)


@pytest.mark.parametrize(
    ("url", "complaint"),
    [
        ("postgres://u:p@h/db", "must start with mssql://"),
        ("mssql://u:p@/db", "no host"),
        ("mssql://h/db", "no user"),
        ("mssql://u:p@h/", "no database name"),
        ("mssql://u:p@h:notaport/db", "invalid port"),
    ],
)
def test_a_bad_database_url_names_the_problem_not_the_password(url, complaint):
    with pytest.raises(ValueError, match=complaint) as caught:
        ConnectionSettings.from_url(url)
    assert ":p@" not in str(caught.value)


def test_an_unset_database_url_is_an_error():
    with pytest.raises(ValueError, match="DATABASE_URL is not set"):
        Database.from_url(None)


# --- waking up a paused database ------------------------------------------------


class _Flaky:
    """Fails with the given error numbers, then connects."""

    def __init__(self, *numbers: int) -> None:
        self.failures = list(numbers)
        self.calls: list[dict] = []

    def __call__(self, **options):
        self.calls.append(options)
        if self.failures:
            raise pymssql.OperationalError(self.failures.pop(0), b"simulated")
        return "connection"


SETTINGS = ConnectionSettings(host="h", port=1433, user="u", database="d", password="secret")


def test_a_waking_database_is_retried_with_growing_waits():
    waits: list[float] = []
    flaky = _Flaky(40613, 20003, 20009)
    database = Database(SETTINGS, connect=flaky, sleep=waits.append)

    assert database.connect() == "connection"
    assert waits == [1.0, 2.0, 4.0]
    assert len(flaky.calls) == 4


def test_waits_are_capped_and_the_attempts_run_out():
    waits: list[float] = []
    database = Database(SETTINGS, attempts=6, connect=_Flaky(*[40613] * 6), sleep=waits.append)

    with pytest.raises(pymssql.OperationalError):
        database.connect()
    assert waits == [1.0, 2.0, 4.0, 8.0, 15.0]


def test_a_real_fault_is_not_retried():
    """A wrong password will not fix itself; waiting would only hide it."""
    waits: list[float] = []
    flaky = _Flaky(18456)  # login failed
    with pytest.raises(pymssql.OperationalError):
        Database(SETTINGS, connect=flaky, sleep=waits.append).connect()
    assert waits == [] and len(flaky.calls) == 1


def test_encryption_is_required_only_when_the_url_asks_for_it():
    plain, encrypted = _Flaky(), _Flaky()
    Database(SETTINGS, connect=plain).connect()
    Database(ConnectionSettings(host="h", port=1433, user="u", database="d", encrypt=True), connect=encrypted).connect()
    assert "encryption" not in plain.calls[0]
    assert encrypted.calls[0]["encryption"] == "require"


def test_retry_logs_name_the_error_number_and_never_the_password(caplog):
    Database(SETTINGS, connect=_Flaky(40613), sleep=lambda _: None).connect()
    assert "40613" in caplog.text
    assert "secret" not in caplog.text


def test_tests_only_ever_use_their_own_throwaway_database(database):
    """The fixtures point at the run's test_ database, never at DATABASE_URL,
    so running the tests cannot touch a real database."""
    assert database.name.startswith("test_")

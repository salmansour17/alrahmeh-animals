"""Shared test fixtures: a real SQL Server database for each test run.

At the start of a run this creates a uniquely named database on the test
server, applies this service's migrations to it once, and drops it at the end.
Before each test the tables are emptied, so no test sees another's rows. That
throwaway database is the only thing in the project that is ever dropped.

Where the test server is:
- TEST_SQLSERVER_URL, a URL with an admin login, for example
  mssql://sa:PASSWORD@localhost:1433/master; or
- MSSQL_SA_PASSWORD alone, for a SQL Server on localhost:1433, which is what
  the compose file and `docker run` in the README start.

The fixtures build Config and Database directly, so no test touches the real
database, and none needs os.environ changed. This is the payoff for create_app
taking a Config (and a Database) instead of reading the environment itself.
"""

from __future__ import annotations

import os
import uuid
from urllib.parse import quote, urlsplit, urlunsplit

import pymssql
import pytest

from config import Config
from db import ConnectionSettings, Database
from migrate import apply_migrations

ADMIN_PASSWORD = "test-admin-password"

# Children before parents, so foreign keys never block the clean-up.
TABLES = ["stripe_payments", "donations"]


def _server_url() -> str:
    url = os.environ.get("TEST_SQLSERVER_URL")
    if url:
        return url
    password = os.environ.get("MSSQL_SA_PASSWORD")
    if not password:
        pytest.exit(
            "Tests need a SQL Server. Start one (see the README) and set MSSQL_SA_PASSWORD, "
            "or TEST_SQLSERVER_URL=mssql://sa:PASSWORD@HOST:1433/master",
            returncode=2,
        )
    return f"mssql://sa:{quote(password, safe='')}@localhost:1433/master"


def _admin_connection(server: ConnectionSettings):
    return pymssql.connect(
        server=server.host,
        port=str(server.port),
        user=server.user,
        password=server.password,
        database="master",
        autocommit=True,
        login_timeout=10,
    )


@pytest.fixture(scope="session")
def database_url() -> str:
    """A fresh database for this test run, with the migrations applied."""
    server_url = _server_url()
    server = ConnectionSettings.from_url(server_url)
    name = f"test_{os.path.basename(os.getcwd())}_{uuid.uuid4().hex[:10]}"
    admin = _admin_connection(server)
    # The name is built here from a fixed prefix and hex digits, never from
    # input, which is why it may be placed in the statement text.
    admin.cursor().execute(f"CREATE DATABASE [{name}]")
    parts = urlsplit(server_url)
    url = urlunsplit((parts.scheme, parts.netloc, f"/{name}", parts.query, ""))
    try:
        apply_migrations(Database.from_url(url))
        yield url
    finally:
        cursor = admin.cursor()
        cursor.execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE")
        cursor.execute(f"DROP DATABASE [{name}]")
        admin.close()


@pytest.fixture
def database(database_url) -> Database:
    """The run's database, emptied before this test, ids starting again at 1."""
    db = Database.from_url(database_url)
    with db.unit_of_work() as connection:
        # The ledger's trigger refuses every DELETE, as it should. Only this
        # clean-up of the throwaway test database switches it off, and only
        # inside this transaction.
        connection.execute("DISABLE TRIGGER tr_donations_append_only ON donations")
        for table in TABLES:
            connection.execute(f"DELETE FROM {table}")
            connection.execute(
                "IF EXISTS (SELECT 1 FROM sys.identity_columns "
                "WHERE object_id = OBJECT_ID(%s) AND last_value IS NOT NULL) "
                "DBCC CHECKIDENT (%s, RESEED, 0) WITH NO_INFOMSGS",
                (table, table),
            )
        connection.execute("ENABLE TRIGGER tr_donations_append_only ON donations")
    return db


@pytest.fixture
def config(database, database_url) -> Config:
    """A Config for this test, pointing at the run's database (already emptied
    by the `database` fixture)."""
    return Config(
        host="0.0.0.0",
        port=8000,
        debug=False,
        database_url=database_url,
        admin_password=ADMIN_PASSWORD,
    )


@pytest.fixture
def client(config, database):
    """A Flask test client. Makes requests without binding a port. The animals
    service is a fake that knows animal 7; tests of the real HTTP call use
    tests/animals_stub.py instead."""
    from app import create_app
    from tests.test_donations_service import FakeAnimalDirectory

    return create_app(config, FakeAnimalDirectory({7}), database).test_client()

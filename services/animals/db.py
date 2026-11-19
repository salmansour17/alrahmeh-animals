"""SQL Server connection handling for this service.

This module is the only place in the service that imports `pymssql`, the
SQL Server driver. Repositories receive a `Database` and ask it for a unit of
work, so no domain code knows which database it talks to or how to reach it.
Each service keeps its own copy of this file rather than sharing a package, so
no service depends on another's code (ADR-6).

Where the database is comes from DATABASE_URL, in this form:

    mssql://USER:PASSWORD@HOST:PORT/DATABASE?encrypt=true

`encrypt=true` is required for Azure SQL, which refuses unencrypted
connections. A password containing @, : or / must be percent-encoded.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pymssql

logger = logging.getLogger(__name__)

# Re-exported so repositories and tests can catch driver errors without
# importing the driver themselves.
DatabaseError = pymssql.DatabaseError
IntegrityError = pymssql.IntegrityError

DEFAULT_PORT = 1433

# Error numbers that mean "the database is not ready yet", so trying again
# shortly will probably work. Anything else (a wrong password, a missing
# database) is a real fault and is raised at once.
#   40613  Azure SQL: database not currently available (resuming from pause)
#   40501  Azure SQL: the service is busy
#   40197  Azure SQL: the service hit an error processing the request
#   20002  pymssql (FreeTDS): connection failed
#   20003  pymssql (FreeTDS): connection timed out
#   20009  pymssql (FreeTDS): server unavailable or does not exist yet
RETRYABLE_ERRORS = frozenset({40613, 40501, 40197, 20002, 20003, 20009})

# A paused Azure SQL database takes up to about a minute to resume. Waiting
# 1, 2, 4, 8, 15, 15 and 15 seconds between eight attempts covers 60 seconds
# before giving up.
DEFAULT_ATTEMPTS = 8
DEFAULT_FIRST_DELAY_S = 1.0
DEFAULT_MAX_DELAY_S = 15.0
LOGIN_TIMEOUT_S = 10
# The health check gives up much sooner: the platform's probes and the deploy
# pipeline wait a few seconds for an answer, and "not ready" is the right
# answer while the database is unreachable. The login timeout does not cover
# looking up the server's name, which inside Docker can take 15 seconds for a
# stopped container, so the whole check also runs against a deadline.
HEALTH_LOGIN_TIMEOUT_S = 3
HEALTH_DEADLINE_S = 5

# Threads for the health check's deadline. A check abandoned at the deadline
# finishes on its own in the background; two threads are plenty for probes
# that arrive every few seconds.
_HEALTH_WORKERS = ThreadPoolExecutor(max_workers=2, thread_name_prefix="health")
QUERY_TIMEOUT_S = 30


@dataclass(frozen=True)
class ConnectionSettings:
    """Where the database is and how to log in, parsed from DATABASE_URL."""

    host: str
    port: int
    user: str
    database: str
    encrypt: bool = False
    # Excluded from repr, so a logged or printed settings object never shows it.
    password: str = field(default="", repr=False)

    @classmethod
    def from_url(cls, url: str) -> ConnectionSettings:
        """Parse mssql://USER:PASSWORD@HOST:PORT/DATABASE?encrypt=true.

        Raises ValueError naming the part that is wrong, never the URL itself,
        because the URL contains the password.
        """
        parts = urlsplit(url)
        if parts.scheme not in ("mssql", "mssql+pymssql"):
            raise ValueError("DATABASE_URL must start with mssql://")
        if not parts.hostname:
            raise ValueError("DATABASE_URL has no host")
        if not parts.username:
            raise ValueError("DATABASE_URL has no user")
        database = parts.path.lstrip("/")
        if not database:
            raise ValueError("DATABASE_URL has no database name")
        try:
            port = parts.port or DEFAULT_PORT
        except ValueError:
            raise ValueError("DATABASE_URL has an invalid port") from None
        encrypt = parse_qs(parts.query).get("encrypt", ["false"])[-1].lower() in ("true", "yes", "1")
        return cls(
            host=parts.hostname,
            port=port,
            user=unquote(parts.username),
            database=unquote(database),
            encrypt=encrypt,
            password=unquote(parts.password or ""),
        )


def _error_number(error: Exception) -> int | None:
    """pymssql puts the SQL Server or FreeTDS error number first in args."""
    if error.args and isinstance(error.args[0], int):
        return error.args[0]
    return None


class Connection:
    """A thin wrapper so repositories write `connection.execute(sql, params)`
    and read rows as dictionaries, whichever driver is underneath."""

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def execute(self, sql: str, params: tuple = ()) -> Any:
        """Run one statement or batch with %s placeholders and return its
        cursor. Values are always sent as parameters, never pasted into the
        SQL text, so a value from a request can never become part of a query."""
        cursor = self._raw.cursor(as_dict=True)
        if params:
            cursor.execute(sql, params)
        else:
            # Without parameters the driver does no % substitution, so the SQL
            # is sent exactly as written.
            cursor.execute(sql)
        return cursor


class Database:
    """Owns the connection settings and hands out transactions."""

    def __init__(
        self,
        settings: ConnectionSettings,
        *,
        appname: str = "alrahmeh",
        attempts: int = DEFAULT_ATTEMPTS,
        first_delay_s: float = DEFAULT_FIRST_DELAY_S,
        max_delay_s: float = DEFAULT_MAX_DELAY_S,
        connect: Callable[..., Any] = pymssql.connect,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._settings = settings
        self._appname = appname
        self._attempts = attempts
        self._first_delay_s = first_delay_s
        self._max_delay_s = max_delay_s
        # Injected so tests can simulate a database that is waking up without
        # waiting for real time to pass.
        self._connect = connect
        self._sleep = sleep

    @classmethod
    def from_url(cls, url: str | None, **options: Any) -> Database:
        """Build from DATABASE_URL. Unset is an error, not a default: the URL
        holds a password, so there is no value it could safely fall back to."""
        if not url:
            raise ValueError("DATABASE_URL is not set")
        return cls(ConnectionSettings.from_url(url), **options)

    @property
    def name(self) -> str:
        return self._settings.database

    def connect(self, retry: bool = True, login_timeout_s: int = LOGIN_TIMEOUT_S) -> Any:
        """Open a connection, retrying with backoff while the database wakes up.

        A new connection per unit of work rather than one shared connection: a
        connection cannot safely serve two requests at once, and the server
        handles requests on several threads. retry=False makes one attempt
        only, for the health check, which must answer quickly either way.
        """
        attempts = self._attempts if retry else 1
        delay = self._first_delay_s
        for attempt in range(1, attempts + 1):
            try:
                return self._open(login_timeout_s)
            except pymssql.Error as error:
                number = _error_number(error)
                if number not in RETRYABLE_ERRORS or attempt == attempts:
                    raise
                # The error number only: the message can include the host and
                # user, and none of it helps more than the number does.
                logger.warning(
                    "Database %s not ready (error %s), attempt %d of %d; retrying in %.0f s",
                    self._settings.database,
                    number,
                    attempt,
                    self._attempts,
                    delay,
                )
                self._sleep(delay)
                delay = min(delay * 2, self._max_delay_s)
        raise AssertionError("unreachable")  # the loop always returns or raises

    def _open(self, login_timeout_s: int) -> Any:
        settings = self._settings
        options: dict[str, Any] = {
            "server": settings.host,
            "port": str(settings.port),
            "user": settings.user,
            "password": settings.password,
            "database": settings.database,
            "login_timeout": login_timeout_s,
            "timeout": QUERY_TIMEOUT_S,
            "charset": "UTF-8",
            "tds_version": "7.4",
            "appname": self._appname,
            "autocommit": False,
        }
        if settings.encrypt:
            options["encryption"] = "require"
        return self._connect(**options)

    @contextmanager
    def unit_of_work(self, retry: bool = True, login_timeout_s: int = LOGIN_TIMEOUT_S) -> Iterator[Connection]:
        """Run a block inside one transaction, then commit or roll back.

        Committing on the way out and rolling back on an exception means a
        half-applied write cannot survive an error, and callers never have to
        remember to commit.
        """
        raw = self.connect(retry=retry, login_timeout_s=login_timeout_s)
        try:
            yield Connection(raw)
            raw.commit()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()

    def check_read_write(self, deadline_s: float = HEALTH_DEADLINE_S) -> None:
        """Prove the service can write to and read from its own database, for
        GET /health. Raises if it cannot, or if it has no answer within
        deadline_s seconds.

        It moves the timestamp on the single row of health_probe (created by a
        migration) and reads it back, so the table never grows. One attempt,
        no retries, and a short login timeout: a database that is still waking
        up should show as not ready, quickly, rather than hold the check.
        """
        future = _HEALTH_WORKERS.submit(self._probe)
        try:
            future.result(timeout=deadline_s)
        except FutureTimeout:
            raise TimeoutError("no answer from the database before the health check's deadline") from None

    def _probe(self) -> None:
        with self.unit_of_work(retry=False, login_timeout_s=HEALTH_LOGIN_TIMEOUT_S) as connection:
            connection.execute("UPDATE health_probe SET checked_at = SYSUTCDATETIME() WHERE id = 1")
            row = connection.execute("SELECT checked_at FROM health_probe WHERE id = 1").fetchone()
        if row is None:
            raise RuntimeError("health_probe has no row")

    def table_names(self) -> list[str]:
        """Tables currently present in this service's database."""
        with self.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT TABLE_NAME AS name FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_TYPE = 'BASE TABLE' ORDER BY TABLE_NAME"
            ).fetchall()
        return [row["name"] for row in rows]

"""One database connection per request (db.py, Database.begin_request).

The same in every service, like db.py itself, except the last test. The
fake connection below counts logins, commits, rollbacks and closes, so each
test can say exactly what reached the database. The last test checks the
same thing on one of this service's real requests, against the test SQL
Server.
"""

from __future__ import annotations

import threading

import pymssql
import pytest

from db import ConnectionSettings, Database


class _FakeCursor:
    def __init__(self, raw: _FakeRaw) -> None:
        self._raw = raw

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._raw.statements.append(sql)
        if self._raw.fail_with is not None:
            error, self._raw.fail_with = self._raw.fail_with, None
            raise error

    def fetchone(self) -> dict:
        return {"checked_at": "now"}


class _FakeRaw:
    """One fake connection: records what was done with it."""

    def __init__(self) -> None:
        self.statements: list[str] = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
        self.fail_with: Exception | None = None
        self.commit_fails_with: Exception | None = None
        self.close_fails_with: Exception | None = None

    def cursor(self, as_dict: bool = False) -> _FakeCursor:
        assert not self.closed, "used after close"
        return _FakeCursor(self)

    def commit(self) -> None:
        if self.commit_fails_with is not None:
            raise self.commit_fails_with
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True
        if self.close_fails_with is not None:
            raise self.close_fails_with


class _Logins:
    """Stands in for pymssql.connect: every call is one login."""

    def __init__(self) -> None:
        self.opened: list[_FakeRaw] = []
        self.lock = threading.Lock()

    def __call__(self, **options) -> _FakeRaw:
        raw = _FakeRaw()
        with self.lock:
            self.opened.append(raw)
        return raw


@pytest.fixture
def logins() -> _Logins:
    return _Logins()


@pytest.fixture
def db(logins) -> Database:
    settings = ConnectionSettings(host="h", port=1433, user="u", database="d", password="p")
    return Database(settings, connect=logins, sleep=lambda _: None)


def _work(db: Database, sql: str = "SELECT 1", **options) -> None:
    with db.unit_of_work(**options) as connection:
        connection.execute(sql)


def test_outside_a_request_each_unit_of_work_logs_in_and_closes(db, logins):
    _work(db)
    _work(db)
    assert len(logins.opened) == 2
    assert all(raw.closed and raw.commits == 1 for raw in logins.opened)


def test_inside_a_request_units_of_work_share_one_connection(db, logins):
    token = db.begin_request()
    for _ in range(4):
        _work(db)
    assert len(logins.opened) == 1
    shared = logins.opened[0]
    # Still four transactions, each committed on its own.
    assert shared.commits == 4
    assert not shared.closed
    db.end_request(token)
    assert shared.closed


def test_a_request_that_never_uses_the_database_opens_nothing(db, logins):
    db.end_request(db.begin_request())
    assert logins.opened == []


def test_a_failed_unit_of_work_rolls_back_and_the_next_one_reuses_the_connection(db, logins):
    token = db.begin_request()
    with pytest.raises(ValueError), db.unit_of_work():
        raise ValueError("a domain rule failed")
    _work(db)
    db.end_request(token)
    assert len(logins.opened) == 1
    assert (logins.opened[0].rollbacks, logins.opened[0].commits) == (1, 1)


@pytest.mark.parametrize("error", [pymssql.OperationalError(20047, b"lost"), pymssql.InterfaceError("closed")])
def test_a_broken_connection_is_dropped_and_the_next_unit_logs_in_again(db, logins, error):
    token = db.begin_request()
    _work(db)
    logins.opened[0].fail_with = error
    with pytest.raises(type(error)):
        _work(db)
    assert logins.opened[0].closed
    _work(db)
    db.end_request(token)
    assert len(logins.opened) == 2
    assert logins.opened[1].commits == 1 and logins.opened[1].closed


def test_a_commit_that_loses_the_connection_drops_it(db, logins):
    token = db.begin_request()
    _work(db)
    logins.opened[0].commit_fails_with = pymssql.OperationalError(20047, b"lost")
    with pytest.raises(pymssql.OperationalError):
        _work(db)
    _work(db)
    db.end_request(token)
    assert len(logins.opened) == 2


def test_dropping_a_connection_survives_close_failing(db, logins, caplog):
    token = db.begin_request()
    _work(db)
    logins.opened[0].fail_with = pymssql.OperationalError(20047, b"lost")
    logins.opened[0].close_fails_with = pymssql.InterfaceError("already gone")
    with pytest.raises(pymssql.OperationalError):
        _work(db)
    db.end_request(token)
    assert "dropped either way" in caplog.text


def test_a_nested_unit_of_work_gets_its_own_connection_and_transaction(db, logins):
    token = db.begin_request()
    with db.unit_of_work() as outer:
        outer.execute("SELECT 1")
        _work(db)
        inner = logins.opened[1]
        assert inner.closed and inner.commits == 1
    db.end_request(token)
    assert len(logins.opened) == 2


def test_share_false_logs_in_even_inside_a_request(db, logins):
    token = db.begin_request()
    _work(db)
    _work(db, share=False)
    db.end_request(token)
    assert len(logins.opened) == 2


def test_the_health_check_never_borrows_the_request_connection(db, logins):
    token = db.begin_request()
    _work(db)
    db.check_read_write()
    db.end_request(token)
    assert len(logins.opened) == 2
    assert "health_probe" in " ".join(logins.opened[1].statements)


def test_after_the_request_each_unit_of_work_has_its_own_connection_again(db, logins):
    db.end_request(db.begin_request())
    _work(db)
    _work(db)
    assert len(logins.opened) == 2


def test_two_requests_on_two_threads_never_share_a_connection(db, logins):
    ready = threading.Barrier(2)

    def request() -> None:
        token = db.begin_request()
        _work(db)
        ready.wait()  # both requests are mid-flight with a connection open
        _work(db)
        db.end_request(token)

    threads = [threading.Thread(target=request) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(logins.opened) == 2
    assert all(raw.commits == 2 and raw.closed for raw in logins.opened)


def test_app_py_defines_everything_before_its_main_block():
    # Run as a script (python app.py), main() starts at the __main__ block, so
    # anything defined below it does not exist yet. The connection helper was
    # once added there: gunicorn and the tests import the whole file first and
    # never noticed, but local development crashed on start.
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8"))
    last = tree.body[-1]
    assert isinstance(last, ast.If)
    assert ast.unparse(last.test) == "__name__ == '__main__'"


# --- On a real request, against the test SQL Server ------------------------


def _count_logins(database: Database, monkeypatch) -> list[int]:
    """Wrap the real driver's connect so the test can count logins."""
    calls: list[int] = []
    real_connect = database._connect

    def counting(**options):
        calls.append(1)
        return real_connect(**options)

    monkeypatch.setattr(database, "_connect", counting)
    return calls


def test_each_request_logs_in_once(client, database, monkeypatch):
    from tests.test_enquiries import MESSAGE, STAFF

    logins = _count_logins(database, monkeypatch)
    assert client.post("/api/enquiries", json=MESSAGE).status_code == 201
    assert client.get("/api/enquiries?handled=false", headers=STAFF).status_code == 200
    assert len(logins) == 2

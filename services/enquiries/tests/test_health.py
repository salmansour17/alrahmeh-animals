"""GET /health: 200 only when this service can read and write its own
database, 503 otherwise, with the build's git commit as `version`."""

from __future__ import annotations

from dataclasses import replace

import pymssql

from app import create_app
from config import load_config
from db import ConnectionSettings, Database


class _Unreachable:
    """A database connection that always fails, as a paused or stopped
    database does. Counts the attempts made."""

    def __init__(self, number: int) -> None:
        self.number = number
        self.attempts = 0

    def __call__(self, **options):
        self.attempts += 1
        raise pymssql.OperationalError(self.number, b"simulated: server password=hunter2 unreachable")


def _down(number: int) -> tuple[Database, _Unreachable]:
    connect = _Unreachable(number)
    settings = ConnectionSettings(host="h", port=1433, user="u", database="d", password="p")
    return Database(settings, connect=connect, sleep=lambda _: None), connect


def test_healthy_when_the_database_can_be_read_and_written(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "db": "ok", "version": "dev"}


def test_the_probe_table_keeps_one_row_however_often_it_is_checked(client, database):
    for _ in range(5):
        assert client.get("/health").status_code == 200
    with database.unit_of_work() as connection:
        rows = connection.execute("SELECT id FROM health_probe").fetchall()
    assert [row["id"] for row in rows] == [1]


def test_unhealthy_when_the_database_cannot_be_reached(config, caplog):
    database, _ = _down(20009)
    response = create_app(config, database=database).test_client().get("/health")

    assert response.status_code == 503
    assert response.get_json() == {"status": "error", "db": "error", "version": "dev"}
    # The reason is logged by number; nothing about it reaches the public.
    assert "20009" in caplog.text
    assert "hunter2" not in caplog.text and "hunter2" not in response.get_data(as_text=True)


def test_a_waking_database_is_reported_at_once_not_retried(config):
    """The health check makes one attempt. Retrying for a minute would only
    make the platform's probe time out instead of hearing "not ready"."""
    database, connect = _down(40613)
    assert create_app(config, database=database).test_client().get("/health").status_code == 503
    assert connect.attempts == 1


def test_version_is_the_build_commit(config, database):
    built = create_app(replace(config, version="3f2a9c1"), database=database).test_client()
    assert built.get("/health").get_json()["version"] == "3f2a9c1"


def test_version_comes_from_git_sha_and_defaults_to_dev(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    assert load_config().version == "dev"
    monkeypatch.setenv("GIT_SHA", "3f2a9c1e")
    assert load_config().version == "3f2a9c1e"
    monkeypatch.setenv("GIT_SHA", "  ")
    assert load_config().version == "dev"

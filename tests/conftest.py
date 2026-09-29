"""Shared test fixtures.

Every fixture here builds its own Config pointing at pytest's `tmp_path`, so no
test touches the real ./data directory and none of them can see each other's
rows. This is the payoff for create_app() taking a Config argument instead of
reading os.environ itself: the redirection needs no environment mutation.
"""

from __future__ import annotations

import pytest

from app import create_app
from config import Config
from db.connection import Database

ADMIN_PASSWORD = "test-admin-password"


@pytest.fixture
def config(tmp_path) -> Config:
    """A Config isolated to this test's temporary directory."""
    return Config(
        host="0.0.0.0",
        port=8000,
        data_dir=tmp_path,
        debug=False,
        admin_password=ADMIN_PASSWORD,
    )


@pytest.fixture
def database(config: Config) -> Database:
    """An initialised, empty database. Domain tests build repositories on this."""
    db = Database(config.database_path)
    db.initialise()
    return db


@pytest.fixture
def client(config: Config):
    """A Flask test client. Makes requests without binding a port."""
    return create_app(config).test_client()

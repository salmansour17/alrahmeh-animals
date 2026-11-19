"""Tests for the admin password guard.

/api/meta/schema stands in for any staff-only endpoint here: the guard is a
decorator, so proving it on one route proves it everywhere it is applied.
"""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from app import create_app
from config import load_config
from tests.conftest import ADMIN_PASSWORD


def _basic_auth(password: str, username: str = "staff") -> dict[str, str]:
    """Build an HTTP Basic Authorization header."""
    raw = f"{username}:{password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def test_correct_password_is_accepted(client):
    response = client.get("/api/meta/schema", headers=_basic_auth(ADMIN_PASSWORD))
    assert response.status_code == 200
    assert "enquiries" in response.get_json()["tables"]


def test_missing_credentials_are_rejected(client):
    response = client.get("/api/meta/schema")
    assert response.status_code == 401
    # No challenge header: it would make a browser prompt for the password and
    # then resend it automatically, which is the cross-site request forgery
    # opening the in-memory staff portal is designed to avoid.
    assert "WWW-Authenticate" not in response.headers


def test_wrong_password_is_rejected(client):
    response = client.get("/api/meta/schema", headers=_basic_auth("not-the-password"))
    assert response.status_code == 401


@pytest.mark.parametrize("username", ["staff", "", "anything-at-all"])
def test_username_is_ignored(client, username):
    """There is one shared secret, not a set of accounts, so only the password
    half of the credential is checked."""
    response = client.get(
        "/api/meta/schema", headers=_basic_auth(ADMIN_PASSWORD, username=username)
    )
    assert response.status_code == 200


def test_unset_password_disables_staff_endpoints(config):
    """With ADMIN_PASSWORD unset the guard fails closed: 503, not open access."""
    client = create_app(replace(config, admin_password=None)).test_client()
    response = client.get("/api/meta/schema", headers=_basic_auth("anything"))
    assert response.status_code == 503
    assert response.get_json()["error"] == "admin_disabled"


def test_public_endpoints_stay_public(config):
    """The guard must not leak onto unprotected routes."""
    client = create_app(replace(config, admin_password=None)).test_client()
    assert client.get("/health").status_code == 200


# --- secrets in configuration -------------------------------------------------


def test_config_repr_never_shows_secrets(monkeypatch):
    """A Config printed in a log line or a failing test must not reveal the
    admin password. The value is a dummy, recognisable if it ever leaked."""
    monkeypatch.setenv("ADMIN_PASSWORD", "dummy-admin-VALUE")

    config = load_config()
    shown = repr(config) + str(config)

    assert config.admin_password == "dummy-admin-VALUE"
    assert "VALUE" not in shown


# --- no web pages any more ----------------------------------------------------


def test_the_service_serves_json_only(client):
    """The website is a separate static build in ui/ (ADR-6). This service has
    no pages: an unknown path, API or not, is a JSON 404."""
    for path in ("/", "/animals", "/api/no-such-thing"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.get_json() == {"error": "not_found"}

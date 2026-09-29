"""Tests for the admin password guard.

/api/meta/schema stands in for any staff-only endpoint here: the guard is a
decorator, so proving it on one route proves it everywhere it is applied.
"""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from app import create_app
from tests.conftest import ADMIN_PASSWORD


def _basic_auth(password: str, username: str = "staff") -> dict[str, str]:
    """Build an HTTP Basic Authorization header."""
    raw = f"{username}:{password}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def test_correct_password_is_accepted(client):
    response = client.get("/api/meta/schema", headers=_basic_auth(ADMIN_PASSWORD))
    assert response.status_code == 200
    assert "animals" in response.get_json()["tables"]


def test_missing_credentials_are_rejected(client):
    response = client.get("/api/meta/schema")
    assert response.status_code == 401
    # The challenge header is what makes a browser offer a login prompt.
    assert response.headers["WWW-Authenticate"].startswith("Basic ")


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
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200

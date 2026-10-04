"""Tests for the admin password guard.

/api/meta/schema stands in for any staff-only endpoint here: the guard is a
decorator, so proving it on one route proves it everywhere it is applied.
"""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

import app as app_module
from app import create_app
from config import DEFAULT_PUBLIC_BASE_URL, load_config
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
    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200


# --- secrets in configuration -------------------------------------------------


def test_config_repr_never_shows_secrets(monkeypatch):
    """A Config printed in a log line or a failing test must not reveal any
    secret. The values here are dummies, recognisable if they ever leaked."""
    monkeypatch.setenv("ADMIN_PASSWORD", "dummy-admin-VALUE")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummyVALUE")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_dummyVALUE")

    config = load_config()
    shown = repr(config) + str(config)

    assert config.stripe_secret_key == "sk_test_dummyVALUE"
    assert "VALUE" not in shown
    assert "sk_test_" not in shown and "whsec_" not in shown


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_PUBLIC_BASE_URL),
        ("https://donate.example.org", "https://donate.example.org"),
        ("https://donate.example.org/", "https://donate.example.org"),
        ("http://localhost:5173", "http://localhost:5173"),
    ],
)
def test_public_base_url_accepts_a_bare_origin(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    else:
        monkeypatch.setenv("PUBLIC_BASE_URL", raw)
    assert load_config().public_base_url == expected


@pytest.mark.parametrize(
    "raw",
    [
        "javascript:alert(1)",
        "ftp://example.org",
        "//evil.example",
        "https://",
        "https://good.example@evil.example",
        "https://example.org/donate",
        "https://example.org?next=https://evil.example",
        "https://example.org#x",
        "example.org",
    ],
)
def test_public_base_url_rejects_anything_but_an_origin(monkeypatch, raw):
    """An invalid value disables payments (None) rather than falling back to
    localhost, which would strand donors on a dead page after paying."""
    monkeypatch.setenv("PUBLIC_BASE_URL", raw)
    assert load_config().public_base_url is None


# --- serving the frontend ----------------------------------------------------


@pytest.fixture
def site(tmp_path, config, monkeypatch):
    """An app serving a stand-in build: index.html and one asset."""
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>", encoding="utf-8")
    (dist / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    (dist / "assets" / "font.woff2").write_bytes(b"wOF2")
    monkeypatch.setattr(app_module, "FRONTEND_DIST", dist)
    return app_module.create_app(config).test_client()


def test_the_built_app_and_its_assets_are_served(site):
    assert b"id=root" in site.get("/").data
    assert site.get("/assets/app.js").data == b"console.log(1)"
    assert site.get("/assets/font.woff2").content_type == "font/woff2"


@pytest.mark.parametrize("path", ["/animals", "/animals/3", "/donate/thanks"])
def test_client_side_routes_get_the_app(site, path):
    response = site.get(path)
    assert response.status_code == 200
    assert b"id=root" in response.data


def test_unknown_api_paths_stay_json_404s(site):
    response = site.get("/api/no-such-thing")
    assert response.status_code == 404
    assert response.get_json() == {"error": "not_found"}


@pytest.mark.parametrize("path", ["/../app.py", "/%2e%2e/app.py", "/assets/../../app.py", "/..%2fapp.py"])
def test_nothing_outside_the_build_can_be_read(site, path):
    response = site.get(path)
    assert b"create_app" not in response.data


def test_a_missing_build_is_a_clear_message_not_a_crash(tmp_path, config, monkeypatch):
    monkeypatch.setattr(app_module, "FRONTEND_DIST", tmp_path / "not-built")
    response = app_module.create_app(config).test_client().get("/animals")
    assert response.status_code == 200
    assert b"has not been built" in response.data

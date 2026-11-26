"""Tests for the admin password guard.

/api/meta/schema stands in for any staff-only endpoint here: the guard is a
decorator, so proving it on one route proves it everywhere it is applied.
"""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from app import create_app
from config import DEFAULT_ANIMALS_TIMEOUT_S, DEFAULT_ANIMALS_URL, DEFAULT_PUBLIC_BASE_URL, load_config
from tests.conftest import ADMIN_PASSWORD


def _basic_auth(password: str, username: str = "staff") -> dict[str, str]:
    """Build an HTTP Basic Authorization header."""
    raw = f"{username}:{password}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}


def test_correct_password_is_accepted(client):
    response = client.get("/api/meta/schema", headers=_basic_auth(ADMIN_PASSWORD))
    assert response.status_code == 200
    assert "donations" in response.get_json()["tables"]


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
    response = client.get("/api/meta/schema", headers=_basic_auth(ADMIN_PASSWORD, username=username))
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
    """A Config printed in a log line or a failing test must not reveal any
    secret. The values here are dummies, recognisable if they ever leaked."""
    monkeypatch.setenv("ADMIN_PASSWORD", "dummy-admin-VALUE")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_dummyVALUE")  # gitleaks:allow (made-up test key)
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_dummyVALUE")

    config = load_config()
    shown = repr(config) + str(config)

    assert config.stripe_secret_key == "sk_test_dummyVALUE"  # gitleaks:allow (made-up test key)
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


# --- where the animals service is (ADR-6) ---------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_ANIMALS_URL),
        ("http://localhost:8001", "http://localhost:8001"),
        ("https://animals.example.org/", "https://animals.example.org"),
        ("not a url", DEFAULT_ANIMALS_URL),
        ("http://animals:8000/api", DEFAULT_ANIMALS_URL),
    ],
)
def test_animals_url_is_a_plain_origin_or_the_default(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("ANIMALS_URL", raising=False)
    else:
        monkeypatch.setenv("ANIMALS_URL", raw)
    assert load_config().animals_url == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, DEFAULT_ANIMALS_TIMEOUT_S),
        ("0.5", 0.5),
        ("5", 5.0),
        ("0", DEFAULT_ANIMALS_TIMEOUT_S),
        ("-1", DEFAULT_ANIMALS_TIMEOUT_S),
        ("soon", DEFAULT_ANIMALS_TIMEOUT_S),
        ("3600", DEFAULT_ANIMALS_TIMEOUT_S),
    ],
)
def test_the_animals_timeout_is_always_bounded(monkeypatch, raw, expected):
    """Zero, negative or huge values would defeat the timeout's purpose, so
    they fall back to the default instead."""
    if raw is None:
        monkeypatch.delenv("ANIMALS_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("ANIMALS_TIMEOUT_S", raw)
    assert load_config().animals_timeout_s == expected


@pytest.mark.parametrize(
    ("name", "raw", "expected"),
    [
        ("ANIMAL_NAMES_TTL_S", None, 300),
        ("ANIMAL_NAMES_TTL_S", "60", 60),
        ("ANIMAL_NAMES_TTL_S", "0", 300),
        ("ANIMAL_NAMES_TTL_S", "3601", 300),
        ("ANIMAL_NAMES_TTL_S", "5 minutes", 300),
        ("ANIMAL_NAMES_CACHE_SIZE", None, 1000),
        ("ANIMAL_NAMES_CACHE_SIZE", "50", 50),
        ("ANIMAL_NAMES_CACHE_SIZE", "-3", 1000),
        ("ANIMAL_NAMES_CACHE_SIZE", "1e9", 1000),
    ],
)
def test_the_name_cache_settings_are_bounded(monkeypatch, name, raw, expected):
    """A zero or negative time to live or size would make the cache useless or
    unbounded, so like PORT they fall back to the default with a warning."""
    if raw is None:
        monkeypatch.delenv(name, raising=False)
    else:
        monkeypatch.setenv(name, raw)
    field = {"ANIMAL_NAMES_TTL_S": "animal_names_ttl_s", "ANIMAL_NAMES_CACHE_SIZE": "animal_names_cache_size"}[name]
    assert getattr(load_config(), field) == expected


# --- no web pages any more ----------------------------------------------------


def test_the_service_serves_json_only(client):
    """The website is a separate static build in ui/ (ADR-6). This service has
    no pages: an unknown path, API or not, is a JSON 404."""
    for path in ("/", "/animals", "/api/no-such-thing"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.get_json() == {"error": "not_found"}

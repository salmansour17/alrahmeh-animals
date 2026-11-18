"""CORS: only the website's own origin may call this service from a browser
(cors.py, CORS_ORIGINS)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app import create_app
from config import load_config

WEBSITE = "https://alrahmehui.z28.web.core.windows.net"
ELSEWHERE = "https://evil.example"
# A write the website really makes to this service, and so must be allowed to
# send as JSON, which is what makes the browser ask first.
POST_PATH = "/api/animals/1/requests"


@pytest.fixture
def site(config, database):
    return create_app(replace(config, cors_origins=frozenset({WEBSITE})), database=database).test_client()


def _preflight(client, origin, method="POST", headers="content-type"):
    return client.options(
        POST_PATH,
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": method,
            "Access-Control-Request-Headers": headers,
        },
    )


def test_the_website_may_read(site):
    response = site.get("/api/health", headers={"Origin": WEBSITE})
    assert response.headers["Access-Control-Allow-Origin"] == WEBSITE
    assert "Origin" in response.headers["Vary"]
    assert "Access-Control-Allow-Credentials" not in response.headers


def test_another_origin_gets_no_permission(site):
    """The answer still comes back (CORS is the browser's rule, not the
    server's), but without the header the browser will not hand it over."""
    response = site.get("/api/health", headers={"Origin": ELSEWHERE})
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_the_preflight_for_a_json_post_is_answered(site):
    """The case the setup guide warns about: the browser asks before a JSON
    POST, and the answer must allow Content-Type, or every form fails."""
    response = _preflight(site, WEBSITE)
    assert response.status_code == 204
    assert response.headers["Access-Control-Allow-Origin"] == WEBSITE
    assert "POST" in response.headers["Access-Control-Allow-Methods"]
    allowed = response.headers["Access-Control-Allow-Headers"].lower()
    assert "content-type" in allowed and "authorization" in allowed


def test_a_preflight_from_another_origin_is_refused(site):
    response = _preflight(site, ELSEWHERE)
    assert response.status_code == 403
    assert "Access-Control-Allow-Origin" not in response.headers


def test_without_cors_origins_no_browser_origin_is_allowed(client):
    assert "Access-Control-Allow-Origin" not in client.get("/api/health", headers={"Origin": WEBSITE}).headers
    assert _preflight(client, WEBSITE).status_code == 403


def test_a_plain_options_request_is_not_mistaken_for_a_preflight(site):
    """Without Access-Control-Request-Method it is not a preflight, so it goes
    to Flask's normal handling."""
    assert site.options("/api/health", headers={"Origin": WEBSITE}).status_code == 200


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, set()),
        ("", set()),
        (WEBSITE, {WEBSITE}),
        (f"{WEBSITE}/, http://localhost:8080", {WEBSITE, "http://localhost:8080"}),
        ("*", set()),
        (f"*, {WEBSITE}", {WEBSITE}),
        ("https://example.org/path, ftp://example.org, example.org", set()),
    ],
)
def test_cors_origins_takes_plain_origins_only_and_never_a_wildcard(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ORIGINS", raw)
    assert load_config().cors_origins == expected

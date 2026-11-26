"""The hardening on the donations service's real routes: the card checkout's
rate limit, the staff password's, the headers on every answer, and the
security events, with canary strings that must never reach a log."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace

import pytest

from donations.service import DonationService, InvalidWebhookSignature
from hardening import SECURITY_HEADERS, HardeningSettings
from security_events import LOGGER_NAME, SecurityEvent, SecurityEvents
from tests.test_donations_routes import STAFF
from tests.test_donations_service import (
    TODAY,
    FakeAnimalDirectory,
    FakeGateway,
    UnreachableAnimalDirectory,
    repository,  # noqa: F401 (fixture)
)

CHECKOUT = {"amount_jod": "10", "purpose": "general"}
INGRESS = "203.0.113.7"  # the address the Container Apps ingress appends
CANARIES = ("canary.CANARY_VALUE@example.com", "CANARY_VALUE_NAME", "CANARY_VALUE_PW", "CANARY_VALUE_TOKEN")


def _from(address: str, spoofed: str = "192.0.2.1") -> dict[str, str]:
    """Headers as the ingress delivers them: whatever the client claimed, then
    the address the ingress saw."""
    return {"X-Forwarded-For": f"{spoofed}, {address}"}


def _basic(password: str) -> dict[str, str]:
    return {"Authorization": "Basic " + base64.b64encode(f"staff:{password}".encode()).decode("ascii")}


@pytest.fixture
def app(config, database):
    from app import create_app

    application = create_app(
        replace(config, cors_origins=frozenset({"https://site.example"})), FakeAnimalDirectory({7}), database
    )

    @application.get("/boom")
    def boom():
        raise RuntimeError("an unexpected failure")

    return application


@pytest.fixture
def http(app):
    return app.test_client()


# --- the public form: starting a card donation ----------------------------------------


def test_the_sixth_checkout_in_a_minute_is_429_with_retry_after(http):
    codes = [http.post("/api/donations/checkout", json=CHECKOUT, headers=_from(INGRESS)).status_code for _ in range(5)]
    assert 429 not in codes  # 503 here: no card keys in tests, but each one counts
    refused = http.post("/api/donations/checkout", json=CHECKOUT, headers=_from(INGRESS))
    assert refused.status_code == 429
    assert refused.get_json()["error"] == "rate_limited"
    assert 1 <= int(refused.headers["Retry-After"]) <= 60
    assert refused.headers["X-Content-Type-Options"] == "nosniff"


def test_inventing_a_forwarded_address_does_not_dodge_the_limit(http):
    for n in range(5):
        http.post("/api/donations/checkout", json=CHECKOUT, headers=_from(INGRESS, spoofed=f"192.0.2.{n}"))
    assert http.post("/api/donations/checkout", json=CHECKOUT, headers=_from(INGRESS, "192.0.2.99")).status_code == 429
    # Another real client is unaffected.
    assert http.post("/api/donations/checkout", json=CHECKOUT, headers=_from("203.0.113.8")).status_code != 429


def test_a_preflight_does_not_count(http):
    for _ in range(10):
        http.options("/api/donations/checkout", headers={**_from(INGRESS), "Origin": "https://site.example"})
    assert http.post("/api/donations/checkout", json=CHECKOUT, headers=_from(INGRESS)).status_code != 429


def test_the_webhook_and_health_are_never_limited(http):
    for _ in range(20):
        assert http.post("/api/donations/stripe/webhook", data=b"{}", headers=_from(INGRESS)).status_code != 429
        assert http.get("/health", headers=_from(INGRESS)).status_code != 429


def test_the_limits_come_from_the_settings(config, database):
    from app import create_app

    strict = HardeningSettings(public_form=replace(HardeningSettings().public_form, limit=1))
    http = create_app(replace(config, hardening=strict), FakeAnimalDirectory({7}), database).test_client()
    http.post("/api/donations/checkout", json=CHECKOUT)
    assert http.post("/api/donations/checkout", json=CHECKOUT).status_code == 429


# --- the staff password ----------------------------------------------------------------


def test_five_wrong_passwords_lock_the_client_out_even_with_the_right_one(http):
    for _ in range(5):
        assert http.get("/api/donations", headers={**_basic("wrong"), **_from(INGRESS)}).status_code == 401
    locked = http.get("/api/donations", headers={**STAFF, **_from(INGRESS)})
    assert locked.status_code == 429
    assert int(locked.headers["Retry-After"]) >= 1
    # Another client is not locked out.
    assert http.get("/api/donations", headers={**STAFF, **_from("203.0.113.8")}).status_code == 200


def test_a_missing_password_is_not_a_guess(http):
    for _ in range(10):
        assert http.get("/api/donations", headers=_from(INGRESS)).status_code == 401
    assert http.get("/api/donations", headers={**STAFF, **_from(INGRESS)}).status_code == 200


def test_a_flood_on_the_form_never_locks_staff_out(http):
    for _ in range(10):
        http.post("/api/donations/checkout", json=CHECKOUT, headers=_from(INGRESS))
    assert http.get("/api/donations", headers={**STAFF, **_from(INGRESS)}).status_code == 200


# --- headers ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("get", "/api/donations/impact", 200),
        ("get", "/api/no-such-thing", 404),
        ("get", "/boom", 500),
        ("get", "/health", 200),
    ],
)
def test_security_headers_on_every_answer(http, method, path, status):
    response = getattr(http, method)(path)
    assert response.status_code == status
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert len(response.headers["X-Request-Id"]) == 32


def test_staff_answers_are_never_cached_and_public_ones_are_left_alone(http):
    assert http.get("/api/donations", headers=STAFF).headers["Cache-Control"] == "no-store"
    assert http.get("/api/donations").headers["Cache-Control"] == "no-store"  # the 401 too
    assert "Cache-Control" not in http.get("/api/donations/impact").headers


def test_cors_is_unchanged(http):
    allowed = http.get("/api/donations/impact", headers={"Origin": "https://site.example"})
    assert allowed.headers["Access-Control-Allow-Origin"] == "https://site.example"
    other = http.get("/api/donations/impact", headers={"Origin": "https://evil.example"})
    assert "Access-Control-Allow-Origin" not in other.headers
    for _ in range(6):
        refused = http.post(
            "/api/donations/checkout", json=CHECKOUT, headers={**_from(INGRESS), "Origin": "https://site.example"}
        )
    # The browser can read the 429, so the page can say "try again later".
    assert refused.status_code == 429
    assert refused.headers["Access-Control-Allow-Origin"] == "https://site.example"


# --- security events, and what never reaches the log -----------------------------------------


def _security_lines(caplog) -> list[dict]:
    return [json.loads(r.getMessage()) for r in caplog.records if r.name == LOGGER_NAME]


def test_events_for_a_wrong_password_and_a_rate_limit_carry_no_personal_data(http, caplog):
    caplog.set_level(logging.INFO)
    name, email, password, token = CANARIES
    for _ in range(6):
        http.get(
            f"/api/donations?token={token}",
            headers={**_basic(password), **_from(INGRESS), "Cookie": f"session={token}"},
        )
    body = {**CHECKOUT, "donor_name": name, "unknown": email}
    for _ in range(7):
        http.post("/api/donations/checkout", json=body, headers=_from(INGRESS))

    lines = _security_lines(caplog)
    events = [line["event"] for line in lines]
    assert events.count("staff_auth_failed") == 5
    assert events.count("rate_limited") == 2  # one per limit, not one per refusal
    staff_failure = next(line for line in lines if line["event"] == "staff_auth_failed")
    assert staff_failure["route"] == "/api/donations"
    assert (staff_failure["status"], staff_failure["reason"]) == (401, "wrong_password")
    everything_logged = "\n".join(r.getMessage() for r in caplog.records)
    for canary in (*CANARIES, INGRESS, "192.0.2.1"):
        assert canary not in everything_logged


def test_an_invalid_webhook_signature_is_an_event_without_the_body(repository, caplog):  # noqa: F811
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    service = DonationService(
        repository, FakeAnimalDirectory({7}), today=lambda: TODAY, gateway=FakeGateway(), events=SecurityEvents("t")
    )
    with pytest.raises(InvalidWebhookSignature):
        service.handle_webhook(b'{"customer_email": "canary.CANARY_VALUE@example.com"}', "forged")
    (line,) = _security_lines(caplog)
    assert (line["event"], line["status"], line["reason"]) == ("webhook_signature_invalid", 400, "bad_signature")
    assert "CANARY_VALUE" not in caplog.text


def test_an_unverified_earmark_at_checkout_is_an_event_with_the_animal_id(repository, caplog):  # noqa: F811
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    service = DonationService(
        repository, UnreachableAnimalDirectory(), today=lambda: TODAY, gateway=FakeGateway(), events=SecurityEvents("t")
    )
    service.start_checkout({**CHECKOUT, "earmarked_animal_id": 7, "donor_name": "CANARY_VALUE_NAME"})
    (line,) = _security_lines(caplog)
    assert (line["event"], line["reason"], line["animal_id"]) == (SecurityEvent.EARMARK_NOT_VERIFIED, "checkout", 7)
    assert "CANARY_VALUE" not in caplog.text


def test_an_unverified_earmark_on_payment_is_an_event(repository, caplog):  # noqa: F811
    from tests.test_donations_service import _paid

    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    service = DonationService(
        repository, UnreachableAnimalDirectory(), today=lambda: TODAY, gateway=FakeGateway(), events=SecurityEvents("t")
    )
    service.confirm_payment(_paid(earmarked_animal_id=7))
    (line,) = _security_lines(caplog)
    assert (line["reason"], line["animal_id"]) == ("payment", 7)

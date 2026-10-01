"""HTTP-level checks for the donation endpoints, plus the composition-root
pieces that join the two domains: the AnimalDirectoryAdapter and the Amman
clock.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone

import pytest
import stripe

import app as app_module
from app import AnimalDirectoryAdapter, create_app
from domains.animals.repository import SqliteAnimalRepository
from domains.animals.service import AnimalService
from tests.conftest import ADMIN_PASSWORD
from tests.test_donations_service import FakeAnimalDirectory
from tests.test_payments import WEBHOOK_SECRET, _Recorder, event, sign

STAFF = {
    "Authorization": "Basic "
    + base64.b64encode(f"staff:{ADMIN_PASSWORD}".encode()).decode("ascii")
}
GIFT = {"amount_jod": "25.500", "purpose": "medical_fund", "donor_name": "Um Khaled"}


def _record(client, body=GIFT) -> dict:
    response = client.post("/api/donations", json=body, headers=STAFF)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


# --- access ------------------------------------------------------------------


@pytest.mark.parametrize(("method", "path"), [("post", "/api/donations"), ("get", "/api/donations"), ("get", "/api/donations/1")])
def test_staff_endpoints_require_the_admin_password(client, method, path):
    assert getattr(client, method)(path, json=GIFT).status_code == 401


def test_writes_fail_closed_without_a_configured_password(config):
    client = create_app(replace(config, admin_password=None)).test_client()
    assert client.post("/api/donations", json=GIFT, headers=STAFF).status_code == 503


@pytest.mark.parametrize("method", ["put", "patch", "delete"])
def test_a_donation_cannot_be_changed_over_http(client, method):
    donation_id = _record(client)["id"]
    response = getattr(client, method)(f"/api/donations/{donation_id}", json=GIFT, headers=STAFF)
    assert response.status_code == 405
    assert response.get_json()["error"] == "method_not_allowed"


# --- what the public sees ----------------------------------------------------


def test_impact_is_public_and_holds_no_donor_data(client):
    _record(client)
    response = client.get("/api/donations/impact")

    assert response.status_code == 200
    body = response.get_json()
    assert body["total_raised"] == {"amount_fils": 25_500, "amount_jod": "25.500"}
    assert "Um Khaled" not in response.get_data(as_text=True)
    assert set(body) == {"total_raised", "donation_count", "animals_helped", "by_purpose"}


def test_staff_record_shows_money_in_both_forms(client):
    donation = _record(client)
    assert donation["amount_fils"] == 25_500
    assert donation["amount_jod"] == "25.500"
    assert donation["donor_name"] == "Um Khaled"


@pytest.mark.parametrize(
    "amount",
    ["25.5555", "1e3", 25.5],
    ids=["too-many-decimals", "exponent", "json-number"],
)
def test_invalid_amounts_are_400(client, amount):
    response = client.post("/api/donations", json={**GIFT, "amount_jod": amount}, headers=STAFF)
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_failed"


def test_validation_errors_never_echo_the_donor_name(client):
    response = client.post(
        "/api/donations", json={**GIFT, "donor_name": "Secret Donor", "purpose": "x"}, headers=STAFF
    )
    assert response.status_code == 400
    assert "Secret Donor" not in response.get_data(as_text=True)


# --- the two domains joined at the composition root --------------------------


def test_earmarking_works_against_real_animals(client):
    animal = client.post(
        "/api/animals",
        json={"name": "Zaytoon", "species": "Dog", "intake_date": "2026-09-01"},
        headers=STAFF,
    ).get_json()

    ok = client.post("/api/donations", json={**GIFT, "earmarked_animal_id": animal["id"]}, headers=STAFF)
    missing = client.post("/api/donations", json={**GIFT, "earmarked_animal_id": 999}, headers=STAFF)

    assert ok.status_code == 201
    assert missing.status_code == 400
    assert "999" in missing.get_json()["detail"]
    assert client.get("/api/donations/impact").get_json()["animals_helped"] == 1


def test_adapter_and_fake_directory_behave_the_same(database):
    """Liskov: the donations service can't tell the adapter from the fake.
    Both take an int and return a bool; neither raises for a missing animal."""
    animals = AnimalService(SqliteAnimalRepository(database), today=lambda: datetime.now().date())
    real_id = animals.admit({"name": "Loz", "species": "Cat", "intake_date": "2026-09-01"}).id

    adapter = AnimalDirectoryAdapter(animals)
    fake = FakeAnimalDirectory({real_id})

    for directory in (adapter, fake):
        assert directory.exists(real_id) is True
        assert directory.exists(999) is False


def test_amman_today_is_three_hours_ahead_of_utc(monkeypatch):
    """At 22:30 UTC on Sep 30 it is already Oct 1 in Amman."""

    class LateEveningUTC(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(app_module, "datetime", LateEveningUTC)
    assert app_module.amman_today().isoformat() == "2026-10-01"


# --- card payments over HTTP, through the real StripeGateway ----------------


@pytest.fixture
def paying_client(config):
    keyed = replace(
        config,
        stripe_secret_key="sk_test_dummy_test_only",
        stripe_webhook_secret=WEBHOOK_SECRET,
        public_base_url="https://donate.example.org",
    )
    return create_app(keyed).test_client()


def _webhook(client, payload: bytes, header: str | None):
    headers = {"Content-Type": "application/json"}
    if header is not None:
        headers["Stripe-Signature"] = header
    return client.post("/api/donations/stripe/webhook", data=payload, headers=headers)


def test_checkout_is_public_and_returns_the_payment_page(paying_client, monkeypatch):
    monkeypatch.setattr(stripe.checkout.Session, "create", _Recorder())
    response = paying_client.post("/api/donations/checkout", json={"amount_jod": "25.500", "purpose": "general"})

    assert response.status_code == 201
    assert response.get_json() == {"checkout_url": "https://checkout.stripe.com/c/pay/cs_test_new"}
    assert paying_client.get("/api/donations/impact").get_json()["donation_count"] == 0


def test_checkout_urls_ignore_the_host_header(paying_client, monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(stripe.checkout.Session, "create", recorder)
    paying_client.post(
        "/api/donations/checkout",
        json={"amount_jod": "5", "purpose": "general"},
        headers={"Host": "evil.example"},
    )
    assert recorder.kwargs["success_url"].startswith("https://donate.example.org/")


def test_checkout_accepts_json_only(paying_client):
    response = paying_client.post("/api/donations/checkout", data="amount_jod=5&purpose=general",
                                  content_type="application/x-www-form-urlencoded")
    assert response.status_code == 415


def test_oversized_bodies_are_refused(paying_client):
    response = paying_client.post("/api/donations/checkout", data="x" * (65 * 1024), content_type="application/json")
    assert response.status_code == 413


def test_a_signed_webhook_records_once_and_a_replay_does_not(paying_client):
    payload = event(metadata={"purpose": "medical_fund"})

    first = _webhook(paying_client, payload, sign(payload))
    replay = _webhook(paying_client, payload, sign(payload))

    assert (first.status_code, first.get_json()) == (200, {"status": "recorded"})
    assert (replay.status_code, replay.get_json()) == (200, {"status": "already_recorded"})
    impact = paying_client.get("/api/donations/impact").get_json()
    assert impact["donation_count"] == 1
    # USD 35.97 charged, recorded at the peg as 25.503 JOD.
    assert impact["total_raised"]["amount_jod"] == "25.503"


@pytest.mark.parametrize("header", [None, "t=1,v1=forged"], ids=["missing", "forged"])
def test_an_unsigned_or_forged_webhook_is_400_and_writes_nothing(paying_client, header):
    response = _webhook(paying_client, event(), header)
    assert (response.status_code, response.get_json()) == (400, {"error": "invalid_signature"})
    assert paying_client.get("/api/donations/impact").get_json()["donation_count"] == 0


def test_other_events_are_acknowledged_and_ignored(paying_client):
    payload = event(event_type="payment_intent.created")
    assert _webhook(paying_client, payload, sign(payload)).get_json() == {"status": "ignored"}


def test_without_keys_both_payment_endpoints_are_503_and_the_rest_works(client):
    assert client.post("/api/donations/checkout", json={"amount_jod": "5", "purpose": "general"}).status_code == 503
    assert _webhook(client, event(), "t=1,v1=x").status_code == 503
    assert client.get("/api/donations/impact").status_code == 200
    assert client.get("/api/animals").status_code == 200


def test_a_live_key_is_refused_by_name_and_never_logged(config, caplog):
    live = replace(
        config,
        stripe_secret_key="sk_live_dummyLIVEVALUE",
        stripe_webhook_secret="whsec_dummyWEBHOOKVALUE",
    )
    client = create_app(live).test_client()

    assert client.post("/api/donations/checkout", json={"amount_jod": "5", "purpose": "general"}).status_code == 503
    assert "live key refused" in caplog.text
    assert "VALUE" not in caplog.text and "sk_live_" not in caplog.text

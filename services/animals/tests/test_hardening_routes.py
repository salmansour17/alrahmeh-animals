"""The hardening on the animals service's real routes: the adoption and
foster form's rate limit, the staff password's, and the headers. The limiter
itself is tested in test_hardening_unit.py."""

from __future__ import annotations

import base64
import json
import logging

from hardening import SECURITY_HEADERS
from security_events import LOGGER_NAME
from tests.test_animals_routes import APPLICANT, STAFF

INGRESS = {"X-Forwarded-For": "192.0.2.1, 203.0.113.7"}
CANARIES = ("canary.CANARY_VALUE@example.com", "CANARY_VALUE_NAME", "CANARY_VALUE_PW")


def _apply(client, **body):
    return client.post("/api/animals/1/requests", json={"kind": "adoption", **APPLICANT, **body}, headers=INGRESS)


def test_the_sixth_request_form_in_a_minute_is_429(client):
    assert 429 not in [_apply(client).status_code for _ in range(5)]
    refused = _apply(client)
    assert (refused.status_code, refused.get_json()["error"]) == (429, "rate_limited")
    assert int(refused.headers["Retry-After"]) >= 1
    assert client.get("/health", headers=INGRESS).status_code != 429


def test_five_wrong_passwords_lock_out_the_staff_routes(client):
    wrong = {"Authorization": "Basic " + base64.b64encode(b"staff:wrong").decode("ascii"), **INGRESS}
    assert [client.get("/api/requests", headers=wrong).status_code for _ in range(5)] == [401] * 5
    assert client.get("/api/requests", headers={**STAFF, **INGRESS}).status_code == 429
    assert client.get("/api/requests", headers=STAFF).status_code == 200  # another client


def test_headers_and_no_store_on_staff_answers_only(client):
    public = client.get("/api/animals")
    for name, value in SECURITY_HEADERS.items():
        assert public.headers[name] == value
    assert public.headers.get("Cache-Control") != "no-store"
    assert client.get("/api/requests", headers=STAFF).headers["Cache-Control"] == "no-store"
    assert client.get("/api/requests").headers["Cache-Control"] == "no-store"  # the 401 too


def test_no_applicant_detail_reaches_the_log(client, caplog):
    caplog.set_level(logging.INFO)
    name, email, password = CANARIES
    for _ in range(7):
        _apply(client, name=name, email=email)
    wrong = {"Authorization": "Basic " + base64.b64encode(f"staff:{password}".encode()).decode("ascii")}
    client.get("/api/requests", headers={**wrong, **INGRESS})
    events = [json.loads(r.getMessage())["event"] for r in caplog.records if r.name == LOGGER_NAME]
    assert events == ["rate_limited", "staff_auth_failed"]
    for canary in (*CANARIES, "203.0.113.7"):
        assert canary not in caplog.text

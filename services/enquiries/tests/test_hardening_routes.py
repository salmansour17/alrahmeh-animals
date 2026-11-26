"""The hardening on the enquiries service's real routes: the contact and
volunteer form's rate limit, the staff password's, and the headers. The
limiter itself is tested in test_hardening_unit.py."""

from __future__ import annotations

import base64
import json
import logging

from hardening import SECURITY_HEADERS
from security_events import LOGGER_NAME
from tests.test_enquiries import MESSAGE, STAFF

INGRESS = {"X-Forwarded-For": "192.0.2.1, 203.0.113.7"}
CANARIES = ("canary.CANARY_VALUE@example.com", "CANARY_VALUE_NAME", "CANARY_VALUE_PW")


def test_the_sixth_message_in_a_minute_is_429(client):
    assert [client.post("/api/enquiries", json=MESSAGE, headers=INGRESS).status_code for _ in range(5)] == [201] * 5
    refused = client.post("/api/enquiries", json=MESSAGE, headers=INGRESS)
    assert (refused.status_code, refused.get_json()["error"]) == (429, "rate_limited")
    assert int(refused.headers["Retry-After"]) >= 1
    assert client.post("/api/enquiries", json=MESSAGE).status_code == 201  # another client
    assert client.get("/health", headers=INGRESS).status_code != 429


def test_five_wrong_passwords_lock_out_the_staff_routes(client):
    wrong = {"Authorization": "Basic " + base64.b64encode(b"staff:wrong").decode("ascii"), **INGRESS}
    assert [client.get("/api/enquiries", headers=wrong).status_code for _ in range(5)] == [401] * 5
    assert client.get("/api/enquiries", headers={**STAFF, **INGRESS}).status_code == 429


def test_headers_and_no_store_on_staff_answers_only(client):
    sent = client.post("/api/enquiries", json=MESSAGE)
    for name, value in SECURITY_HEADERS.items():
        assert sent.headers[name] == value
    assert sent.headers.get("Cache-Control") != "no-store"
    assert client.get("/api/enquiries", headers=STAFF).headers["Cache-Control"] == "no-store"
    assert client.get("/api/enquiries").headers["Cache-Control"] == "no-store"  # the 401 too


def test_no_sender_detail_reaches_the_log(client, caplog):
    caplog.set_level(logging.INFO)
    name, email, password = CANARIES
    for _ in range(7):
        client.post("/api/enquiries", json={**MESSAGE, "name": name, "email": email}, headers=INGRESS)
    wrong = {"Authorization": "Basic " + base64.b64encode(f"staff:{password}".encode()).decode("ascii")}
    client.get("/api/enquiries", headers={**wrong, **INGRESS})
    events = [json.loads(r.getMessage())["event"] for r in caplog.records if r.name == LOGGER_NAME]
    assert events == ["rate_limited", "staff_auth_failed"]
    for canary in (*CANARIES, "203.0.113.7"):
        assert canary not in caplog.text

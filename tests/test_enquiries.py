"""Tests for the enquiries domain: the contact and volunteer form."""

from __future__ import annotations

import base64
import re
from dataclasses import replace

import pytest

from app import create_app
from db.connection import SCHEMA_PATH
from domains.enquiries.models import Topic, ValidationError
from domains.enquiries.repository import SqliteEnquiryRepository
from domains.enquiries.service import EnquiryNotFound, EnquiryService
from tests.conftest import ADMIN_PASSWORD

STAFF = {
    "Authorization": "Basic " + base64.b64encode(f"staff:{ADMIN_PASSWORD}".encode()).decode("ascii")
}
MESSAGE = {
    "topic": "volunteer",
    "name": "Secret Sender",
    "email": "secret.sender@example.org",
    "subject": "Weekend walks",
    "message": "I can walk dogs on Saturdays.",
}
PRIVATE = ("Secret Sender", "secret.sender@example.org", "Saturdays")


@pytest.fixture
def enquiries(database) -> EnquiryService:
    return EnquiryService(SqliteEnquiryRepository(database))


# --- the service -------------------------------------------------------------


def test_topic_enum_matches_the_schema_check_constraint():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    allowed = re.search(r"CHECK \(topic IN \(([^)]*)\)\)", schema).group(1)
    assert {v.strip().strip("'") for v in allowed.split(",")} == {t.value for t in Topic}


def test_a_message_is_stored_unhandled_and_listed_newest_first(enquiries):
    enquiries.receive(MESSAGE)
    enquiries.receive({**MESSAGE, "topic": "question", "subject": "Opening hours?"})

    listed = enquiries.list_enquiries()

    assert [e.subject for e in listed] == ["Opening hours?", "Weekend walks"]
    assert listed[1].topic is Topic.VOLUNTEER and listed[1].handled is False


def test_marking_handled_is_idempotent_and_filters(enquiries):
    enquiries.receive(MESSAGE)
    enquiries.receive({**MESSAGE, "subject": "Second"})
    first = enquiries.list_enquiries()[-1]

    assert enquiries.mark_handled(first.id).handled is True
    assert enquiries.mark_handled(first.id).handled is True  # again: no error, no change

    assert [e.subject for e in enquiries.list_enquiries(handled="false")] == ["Second"]
    assert [e.subject for e in enquiries.list_enquiries(handled="true")] == ["Weekend walks"]


def test_pagination(enquiries):
    for n in range(3):
        enquiries.receive({**MESSAGE, "subject": f"Message {n}"})
    assert [e.subject for e in enquiries.list_enquiries(limit="2", offset="1")] == ["Message 1", "Message 0"]


def test_honeypot_is_accepted_silently_and_stores_nothing(enquiries):
    enquiries.receive({**MESSAGE, "website": "http://spam.example"})
    enquiries.receive({"website": "x", "topic": "nonsense"})  # even invalid bot input
    assert enquiries.list_enquiries() == []


def test_unknown_message(enquiries):
    with pytest.raises(EnquiryNotFound):
        enquiries.mark_handled(999)


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        (None, "JSON object"),
        ({k: v for k, v in MESSAGE.items() if k != "subject"}, "missing field(s): subject"),
        ({**MESSAGE, "phone": "079"}, "unknown field(s): phone"),
        ({**MESSAGE, "topic": "complaint"}, "topic must be one of"),
        ({**MESSAGE, "name": " "}, "name must be a non-empty string"),
        ({**MESSAGE, "subject": "x" * 151}, "at most 150"),
        ({**MESSAGE, "message": "x" * 4001}, "at most 4000"),
        ({**MESSAGE, "email": "secret.sender.example.org"}, "must look like"),
        ({**MESSAGE, "email": "secret@sender"}, "must look like"),
    ],
)
def test_invalid_messages_are_rejected_without_echoing_personal_data(enquiries, payload, complaint):
    with pytest.raises(ValidationError, match=re.escape(complaint)) as raised:
        enquiries.receive(payload)
    assert "secret" not in str(raised.value).lower()
    assert enquiries.list_enquiries() == []


@pytest.mark.parametrize(
    ("handled", "limit", "offset", "complaint"),
    [("maybe", None, None, "handled must be"), (None, "0", None, "limit must be between"),
     (None, "500", None, "limit must be between"), (None, None, "-1", "offset must be a whole number")],
)
def test_bad_list_filters_are_rejected(enquiries, handled, limit, offset, complaint):
    with pytest.raises(ValidationError, match=complaint):
        enquiries.list_enquiries(handled, limit, offset)


# --- over HTTP ---------------------------------------------------------------


def test_the_public_can_send_and_gets_no_id_back(client):
    response = client.post("/api/enquiries", json=MESSAGE)
    assert (response.status_code, response.get_json()) == (201, {"status": "received"})


def test_a_honeypot_gets_the_identical_answer(client):
    real = client.post("/api/enquiries", json=MESSAGE)
    bot = client.post("/api/enquiries", json={**MESSAGE, "website": "http://spam.example"})
    assert (bot.status_code, bot.get_json()) == (real.status_code, real.get_json())
    assert len(client.get("/api/enquiries", headers=STAFF).get_json()["enquiries"]) == 1


def test_the_form_accepts_json_only(client):
    response = client.post("/api/enquiries", data="topic=question", content_type="text/plain")
    assert response.status_code == 415


@pytest.mark.parametrize(("method", "path"), [("get", "/api/enquiries"), ("post", "/api/enquiries/1/handled")])
def test_the_public_cannot_read_or_handle_messages(client, method, path):
    assert getattr(client, method)(path).status_code == 401


def test_staff_endpoints_fail_closed_without_a_password(config):
    client = create_app(replace(config, admin_password=None)).test_client()
    assert client.get("/api/enquiries", headers=STAFF).status_code == 503


def test_staff_read_and_mark_handled(client):
    client.post("/api/enquiries", json=MESSAGE)
    [message] = client.get("/api/enquiries", headers=STAFF).get_json()["enquiries"]
    assert message["email"] == "secret.sender@example.org"

    handled = client.post(f"/api/enquiries/{message['id']}/handled", headers=STAFF)
    assert handled.get_json()["handled"] is True
    assert client.post("/api/enquiries/999/handled", headers=STAFF).status_code == 404
    assert client.get("/api/enquiries?handled=maybe", headers=STAFF).status_code == 400


def test_sender_details_never_reach_errors_or_logs(client, caplog):
    client.post("/api/enquiries", json=MESSAGE)
    bad = client.post("/api/enquiries", json={**MESSAGE, "email": "not-an-email"})
    for value in PRIVATE:
        assert value not in bad.get_data(as_text=True)
        assert value not in caplog.text

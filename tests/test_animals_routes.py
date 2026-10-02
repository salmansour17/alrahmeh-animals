"""HTTP-level checks for the animal endpoints.

Not about business rules (test_animals_service covers those) but about what the
routing layer promises: which endpoints need the admin password, what the
public can and cannot see, and that each domain error becomes the right status
code with a JSON body.
"""

from __future__ import annotations

import base64
from dataclasses import replace

import pytest

from app import create_app
from tests.conftest import ADMIN_PASSWORD

STAFF = {
    "Authorization": "Basic "
    + base64.b64encode(f"staff:{ADMIN_PASSWORD}".encode()).decode("ascii")
}
ANIMAL = {"name": "Zaytoon", "species": "Dog", "intake_date": "2026-09-01", "notes": "Bites vets."}


def _admit(client) -> int:
    response = client.post("/api/animals", json=ANIMAL, headers=STAFF)
    assert response.status_code == 201
    return response.get_json()["id"]


@pytest.mark.parametrize(
    "path",
    ["/api/animals", "/api/animals/1/transitions", "/api/animals/1/medical-records"],
)
def test_writes_require_the_admin_password(client, path):
    response = client.post(path, json={})
    assert response.status_code == 401


def test_writes_fail_closed_without_a_configured_password(config):
    client = create_app(replace(config, admin_password=None)).test_client()
    response = client.post("/api/animals", json=ANIMAL, headers=STAFF)
    assert response.status_code == 503


def test_staff_view_requires_the_admin_password(client):
    animal_id = _admit(client)
    assert client.get(f"/api/animals/{animal_id}/staff").status_code == 401


def test_public_view_hides_notes_and_non_vaccination_records(client):
    animal_id = _admit(client)
    for record_type, description in [("vaccination", "Rabies"), ("treatment", "Tick fever")]:
        client.post(
            f"/api/animals/{animal_id}/medical-records",
            json={"record_type": record_type, "description": description, "occurred_on": "2026-09-05"},
            headers=STAFF,
        )

    public = client.get(f"/api/animals/{animal_id}").get_json()
    listed = client.get("/api/animals").get_json()["animals"][0]
    staff = client.get(f"/api/animals/{animal_id}/staff", headers=STAFF).get_json()

    assert "notes" not in public and "notes" not in listed
    assert public["vaccinations"] == [{"description": "Rabies", "occurred_on": "2026-09-05"}]
    assert "Tick fever" not in str(public)
    assert staff["notes"] == "Bites vets."
    assert {r["description"] for r in staff["medical_records"]} == {"Rabies", "Tick fever"}


@pytest.mark.parametrize(
    ("method", "path", "body", "status", "error"),
    [
        ("post", "/api/animals", {"name": "Zaytoon"}, 400, "validation_failed"),
        ("get", "/api/animals?status=lost", None, 400, "validation_failed"),
        ("get", "/api/animals/999", None, 404, "not_found"),
        ("post", "/api/animals/{id}/transitions", {"to": "adopted"}, 409, "illegal_transition"),
        ("get", "/api/no-such-thing", None, 404, "not_found"),
    ],
)
def test_errors_map_to_status_codes_with_json_bodies(client, method, path, body, status, error):
    path = path.format(id=_admit(client))
    response = getattr(client, method)(path, json=body, headers=STAFF)

    assert response.status_code == status
    assert response.get_json()["error"] == error


def test_legal_transition_returns_the_updated_animal(client):
    animal_id = _admit(client)
    response = client.post(
        f"/api/animals/{animal_id}/transitions", json={"to": "fostering"}, headers=STAFF
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "fostering"


def test_non_json_body_is_a_validation_error_not_a_crash(client):
    response = client.post(
        "/api/animals", data="name=Zaytoon", content_type="text/plain", headers=STAFF
    )
    assert response.status_code == 400


def test_placement_stats_are_public(client):
    response = client.get("/api/animals/stats")
    assert response.status_code == 200
    assert response.get_json() == {"available": 0, "fostering": 0, "pending": 0, "adopted": 0}


# --- adoption and foster requests over HTTP ---------------------------------

APPLICANT = {"name": "Secret Applicant", "email": "secret.applicant@example.org", "message": "Private note"}
PRIVATE = ("Secret Applicant", "secret.applicant@example.org", "Private note")


def _apply(client, animal_id, kind="adoption", **extra):
    return client.post(f"/api/animals/{animal_id}/requests", json={"kind": kind, **APPLICANT, **extra})


def _staff_requests(client):
    return client.get("/api/requests", headers=STAFF).get_json()["requests"]


def test_the_public_can_ask_and_gets_no_id_back(client):
    animal_id = _admit(client)
    response = _apply(client, animal_id)
    assert (response.status_code, response.get_json()) == (201, {"status": "received"})
    assert len(_staff_requests(client)) == 1


def test_a_honeypot_gets_the_identical_answer_and_stores_nothing(client):
    animal_id = _admit(client)
    real = _apply(client, animal_id)
    bot = _apply(client, animal_id, website="http://spam.example")
    assert (bot.status_code, bot.get_json()) == (real.status_code, real.get_json())
    assert len(_staff_requests(client)) == 1


def test_the_request_form_accepts_json_only(client):
    animal_id = _admit(client)
    response = client.post(f"/api/animals/{animal_id}/requests", data="kind=adoption", content_type="text/plain")
    assert response.status_code == 415


@pytest.mark.parametrize(
    ("method", "path"),
    [("get", "/api/requests"), ("post", "/api/requests/1/decision")],
)
def test_the_public_cannot_read_or_decide_requests(client, method, path):
    assert getattr(client, method)(path, json={"outcome": "approved"}).status_code == 401


def test_request_endpoints_fail_closed_without_a_password(config):
    client = create_app(replace(config, admin_password=None)).test_client()
    assert client.get("/api/requests", headers=STAFF).status_code == 503


def test_applicant_data_never_reaches_public_json_errors_or_logs(client, caplog):
    animal_id = _admit(client)
    _apply(client, animal_id)
    bad = _apply(client, animal_id, email="not-an-email")

    public = (
        client.get("/api/animals").get_data(as_text=True)
        + client.get(f"/api/animals/{animal_id}").get_data(as_text=True)
        + client.get("/api/animals/stats").get_data(as_text=True)
        + bad.get_data(as_text=True)
    )
    for value in PRIVATE:
        assert value not in public
        assert value not in caplog.text
    staff = client.get("/api/requests", headers=STAFF).get_data(as_text=True)
    assert all(value in staff for value in PRIVATE)


def test_staff_approve_then_withdraw_an_adoption(client):
    animal_id = _admit(client)
    _apply(client, animal_id)
    request_id = _staff_requests(client)[0]["id"]

    approved = client.post(f"/api/requests/{request_id}/decision", json={"outcome": "approved"}, headers=STAFF)
    assert approved.get_json()["outcome"] == "approved"
    assert client.get(f"/api/animals/{animal_id}").get_json()["status"] == "pending"

    withdrawn = client.post(f"/api/requests/{request_id}/decision", json={"outcome": "declined"}, headers=STAFF)
    assert withdrawn.status_code == 200
    assert client.get(f"/api/animals/{animal_id}").get_json()["status"] == "available"

    again = client.post(f"/api/requests/{request_id}/decision", json={"outcome": "approved"}, headers=STAFF)
    assert (again.status_code, again.get_json()["error"]) == (409, "already_decided")


@pytest.mark.parametrize(
    ("setup", "kind", "status", "error"),
    [
        ("adopted", "adoption", 409, "request_not_accepted"),
        (None, "sponsor", 400, "validation_failed"),
    ],
)
def test_request_errors_map_to_status_codes(client, setup, kind, status, error):
    animal_id = _admit(client)
    if setup == "adopted":
        for step in ("pending", "adopted"):
            client.post(f"/api/animals/{animal_id}/transitions", json={"to": step}, headers=STAFF)
    response = _apply(client, animal_id, kind=kind)
    assert (response.status_code, response.get_json()["error"]) == (status, error)


def test_unknown_request_is_404(client):
    response = client.post("/api/requests/999/decision", json={"outcome": "approved"}, headers=STAFF)
    assert (response.status_code, response.get_json()["error"]) == (404, "not_found")

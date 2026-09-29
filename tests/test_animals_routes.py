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

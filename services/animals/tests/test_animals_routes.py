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
from tests.test_animals_service import image_bytes, opened

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
        # Beyond SQLite's largest integer: a 404, not an overflow inside sqlite3.
        ("get", "/api/animals/99999999999999999999999", None, 404, "not_found"),
        ("post", "/api/animals/99999999999999999999999/requests", {"kind": "adoption"}, 404, "not_found"),
    ],
)
def test_errors_map_to_status_codes_with_json_bodies(client, method, path, body, status, error):
    path = path.format(id=_admit(client))
    response = getattr(client, method)(path, json=body, headers=STAFF)

    assert response.status_code == status
    assert response.get_json()["error"] == error


def test_sample_animals_are_added_once_to_an_empty_database(config):
    with_samples = replace(config, sample_animals=True)
    animals = create_app(with_samples).test_client().get("/api/animals").get_json()["animals"]
    # A restart finds animals already there and adds nothing.
    again = create_app(with_samples).test_client().get("/api/animals").get_json()["animals"]

    assert len(animals) == len(again) == 6
    assert {a["status"] for a in animals} == {"available", "fostering", "adopted"}


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
    assert response.get_json() == {
        "available": 0, "fostering": 0, "pending": 0, "adopted": 0, "homes_found": 0,
    }


def test_offline_adoptions_are_staff_only_and_count_towards_homes_found(client):
    entry = {"animal_count": 300, "adopted_on": "2026-09-30", "note": "Before the website"}
    assert client.post("/api/animals/offline-adoptions", json=entry).status_code == 401
    assert client.get("/api/animals/offline-adoptions").status_code == 401

    recorded = client.post("/api/animals/offline-adoptions", json=entry, headers=STAFF)
    assert recorded.status_code == 201
    animal_id = _admit(client)
    for step in ("pending", "adopted"):
        client.post(f"/api/animals/{animal_id}/transitions", json={"to": step}, headers=STAFF)

    stats = client.get("/api/animals/stats").get_json()
    assert (stats["adopted"], stats["homes_found"]) == (1, 301)
    listed = client.get("/api/animals/offline-adoptions", headers=STAFF).get_json()["offline_adoptions"]
    assert listed == [{**entry, "id": recorded.get_json()["id"]}]
    bad = client.post("/api/animals/offline-adoptions", json={**entry, "animal_count": 0}, headers=STAFF)
    assert bad.status_code == 400


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


# --- photos over HTTP --------------------------------------------------------


def _upload(client, animal_id, data, content_type="image/jpeg", headers=STAFF):
    return client.put(
        f"/api/animals/{animal_id}/photo", data=data, headers={**headers, "Content-Type": content_type}
    )


def test_staff_upload_and_the_public_sees_the_photo(client):
    animal_id = _admit(client)
    uploaded = _upload(client, animal_id, image_bytes(gps=True))
    assert uploaded.status_code == 200
    url = uploaded.get_json()["photo_url"]

    assert client.get(f"/api/animals/{animal_id}").get_json()["photo_url"] == url
    assert client.get("/api/animals").get_json()["animals"][0]["photo_url"] == url

    photo = client.get(url)
    assert photo.status_code == 200
    assert photo.content_type == "image/webp"
    assert photo.headers["X-Content-Type-Options"] == "nosniff"
    assert "immutable" in photo.headers["Cache-Control"]
    assert client.get(f"/api/animals/{animal_id}/photo").headers["Cache-Control"] == "no-cache"
    # The GPS proof, end to end: what visitors download has no metadata at all.
    assert dict(opened(photo.data).getexif()) == {}


def test_a_replaced_photo_gets_a_new_address(client):
    animal_id = _admit(client)
    first = _upload(client, animal_id, image_bytes()).get_json()["photo_url"]
    second = _upload(client, animal_id, image_bytes(size=(80, 60))).get_json()["photo_url"]
    assert first != second


def test_the_public_cannot_upload(client):
    animal_id = _admit(client)
    assert _upload(client, animal_id, image_bytes(), headers={}).status_code == 401


def test_the_size_limit_is_raised_for_the_photo_route_only(client):
    animal_id = _admit(client)
    eleven_mb = b"\xff\xd8\xff" + b"0" * (11 * 1024 * 1024)
    too_big = _upload(client, animal_id, eleven_mb)
    assert too_big.status_code == 413
    assert "at most 10 MB" in too_big.get_json()["detail"]
    # A phone-sized file fits under the photo limit (it fails later, as not an image)...
    assert _upload(client, animal_id, b"0" * (5 * 1024 * 1024)).status_code == 400
    # ...but every other route still refuses anything over 64 KiB.
    big = client.post("/api/animals", data=b"0" * (100 * 1024), headers={**STAFF, "Content-Type": "application/json"})
    assert big.status_code == 413


@pytest.mark.parametrize(
    ("data", "content_type", "status", "error"),
    [
        (b"hello", "text/plain", 415, "unsupported_media_type"),
        (b"not really a jpeg", "image/jpeg", 400, "validation_failed"),
    ],
)
def test_bad_uploads_are_refused(client, data, content_type, status, error):
    response = _upload(client, _admit(client), data, content_type)
    assert (response.status_code, response.get_json()["error"]) == (status, error)


def test_missing_animal_or_photo_is_404(client):
    assert _upload(client, 999, image_bytes()).status_code == 404
    animal_id = _admit(client)
    assert client.get(f"/api/animals/{animal_id}/photo").status_code == 404
    assert client.get(f"/api/animals/{animal_id}").get_json()["photo_url"] is None


# --- public profile details over HTTP -------------------------------------------


def test_staff_write_the_profile_and_the_public_read_it_formatted(client):
    animal_id = _admit(client)
    details = {"born_on": "2026-01-15", "colour": "Rich golden", "personality": "Friendly",
               "weight_kg": "12.5", "about": "Loves everyone he meets."}

    assert client.put(f"/api/animals/{animal_id}/profile", json=details).status_code == 401
    saved = client.put(f"/api/animals/{animal_id}/profile", json=details, headers=STAFF)
    assert saved.status_code == 200

    profile = client.get(f"/api/animals/{animal_id}").get_json()["profile"]
    assert profile["weight"] == "12.5 kg" and profile["weight_kg"] == "12.5"
    assert profile["colour"] == "Rich golden" and profile["about"] == "Loves everyone he meets."
    assert profile["age"].endswith("months")
    assert client.get(f"/api/animals/{animal_id}/staff", headers=STAFF).get_json()["profile"] == profile


def test_an_animal_without_a_profile_has_empty_details(client):
    profile = client.get(f"/api/animals/{_admit(client)}").get_json()["profile"]
    assert set(profile.values()) == {None}


def test_a_bad_profile_is_400(client):
    response = client.put(f"/api/animals/{_admit(client)}/profile", json={"weight_kg": 12}, headers=STAFF)
    assert (response.status_code, response.get_json()["error"]) == (400, "validation_failed")


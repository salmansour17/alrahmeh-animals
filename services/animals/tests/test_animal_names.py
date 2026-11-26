"""GET /api/animals/names: many animals' names in one request, for the
donations service's staff list (the second server-to-server flow)."""

from __future__ import annotations

import pytest

from animals.models import MAX_NAME_IDS, ValidationError, parse_id_list
from tests.test_animals_routes import ANIMAL, STAFF


def _admit(client, name: str) -> int:
    return client.post("/api/animals", json={**ANIMAL, "name": name}, headers=STAFF).get_json()["id"]


def test_names_for_several_ids_in_one_request(client):
    luna, rocky = _admit(client, "Luna"), _admit(client, "Rocky")
    response = client.get(f"/api/animals/names?ids={rocky},{luna}")
    assert response.status_code == 200
    assert response.get_json() == {"animals": [{"id": luna, "name": "Luna"}, {"id": rocky, "name": "Rocky"}]}


def test_duplicates_count_once_and_unknown_ids_are_simply_absent(client):
    luna = _admit(client, "Luna")
    body = client.get(f"/api/animals/names?ids={luna},{luna},999").get_json()
    assert body == {"animals": [{"id": luna, "name": "Luna"}]}


def test_only_ids_and_names_come_back(client):
    luna = _admit(client, "Luna")
    (animal,) = client.get(f"/api/animals/names?ids={luna}").get_json()["animals"]
    assert set(animal) == {"id", "name"}  # never notes, status or anything staff-only


@pytest.mark.parametrize(
    "query",
    ["", "?ids=", "?ids=1,,2", "?ids=1,x", "?ids=-1", "?ids=0", "?ids=1.5", "?ids=١", f"?ids={2**63}"],
)
def test_malformed_ids_are_400(client, query):
    response = client.get(f"/api/animals/names{query}")
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_failed"


def test_too_many_ids_are_refused(client):
    too_many = ",".join(str(i) for i in range(1, MAX_NAME_IDS + 2))
    assert client.get(f"/api/animals/names?ids={too_many}").status_code == 400
    # Duplicates do not count towards the limit.
    assert client.get(f"/api/animals/names?ids={','.join(['1'] * (MAX_NAME_IDS + 5))}").status_code == 200


def test_the_names_route_and_the_animal_route_do_not_shadow_each_other(client):
    luna = _admit(client, "Luna")
    assert client.get("/api/animals/names?ids=1").get_json() == {"animals": [{"id": luna, "name": "Luna"}]}
    assert client.get(f"/api/animals/{luna}").get_json()["name"] == "Luna"


def test_one_query_whatever_the_number_of_ids(client, monkeypatch):
    import db

    ids = [_admit(client, f"Animal {n}") for n in range(5)]
    statements: list[tuple[str, tuple]] = []
    real_execute = db.Connection.execute

    def recording(self, sql, params=()):
        statements.append((sql, params))
        return real_execute(self, sql, params)

    monkeypatch.setattr(db.Connection, "execute", recording)
    client.get("/api/animals/names?ids=" + ",".join(map(str, ids)))
    (query,) = [(sql, params) for sql, params in statements if "OPENJSON" in sql]
    # The ids travel as one parameter; the SQL text never contains them.
    assert query[1] == (f"[{', '.join(map(str, ids))}]",)
    assert not any(str(i) in query[0] for i in ids)


def test_parse_id_list_keeps_the_order_given():
    assert parse_id_list(" 3, 1,3 ,5") == (3, 1, 5)
    with pytest.raises(ValidationError):
        parse_id_list(None)

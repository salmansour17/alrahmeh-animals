"""Animal names on the staff donation list: the second server-to-server flow
(ADR-6) and the app-level cache in front of it (name_cache.py).

The cache is tested with a fake clock and a counting fake source, so no test
waits for real time. The HTTP adapter is tested over real HTTP against the
stand-in animals service, and the last tests run the whole donations app
against that stand-in, across the seam.
"""

from __future__ import annotations

import threading
import time

import pytest

from donations.animals_client import HttpAnimalDirectory, HttpAnimalNames
from donations.name_cache import CachedAnimalNames
from donations.service import AnimalsUnavailable, DonationService
from tests.animals_stub import AnimalsStub
from tests.test_animals_client import _closed_port
from tests.test_donations_routes import STAFF
from tests.test_donations_service import TODAY, FakeAnimalDirectory, repository  # noqa: F401 (fixture)

TTL_S = 300


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class CountingNames:
    """A fake AnimalNames that records every call and can be told to fail."""

    def __init__(self, known: dict[int, str]) -> None:
        self.known = known
        self.calls: list[set[int]] = []
        self.down = False

    def names(self, animal_ids):
        wanted = set(animal_ids)
        self.calls.append(wanted)
        if self.down:
            raise AnimalsUnavailable("animals service down")
        return {i: self.known[i] for i in wanted if i in self.known}


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def source() -> CountingNames:
    return CountingNames({1: "Luna", 2: "Simba", 3: "Rocky"})


@pytest.fixture
def cache(source, clock) -> CachedAnimalNames:
    return CachedAnimalNames(source, ttl_s=TTL_S, max_entries=10, clock=clock)


# --- the cache --------------------------------------------------------------------


def test_a_fresh_entry_is_answered_from_memory(cache, source):
    assert cache.names({1, 2}) == {1: "Luna", 2: "Simba"}
    assert cache.names({2, 1}) == {1: "Luna", 2: "Simba"}
    assert source.calls == [{1, 2}]


def test_only_the_missing_ids_are_fetched(cache, source):
    cache.names({1})
    assert cache.names({1, 3}) == {1: "Luna", 3: "Rocky"}
    assert source.calls == [{1}, {3}]


def test_an_expired_entry_is_fetched_again(cache, source, clock):
    cache.names({1})
    clock.now += TTL_S - 1
    cache.names({1})
    clock.now += 2  # past the time to live
    cache.names({1})
    assert source.calls == [{1}, {1}]


def test_a_failure_is_not_cached(cache, source):
    source.down = True
    with pytest.raises(AnimalsUnavailable):
        cache.names({1})
    source.down = False
    assert cache.names({1}) == {1: "Luna"}
    assert len(source.calls) == 2


def test_an_unknown_id_is_not_cached(cache, source):
    assert cache.names({999}) == {}
    cache.names({999})
    assert source.calls == [{999}, {999}]


def test_the_oldest_entries_go_first_when_the_cache_is_full(source, clock):
    source.known = {i: f"Animal {i}" for i in range(1, 6)}
    cache = CachedAnimalNames(source, ttl_s=TTL_S, max_entries=3, clock=clock)
    for animal_id in (1, 2, 3, 4):
        clock.now += 1
        cache.names({animal_id})
    assert len(cache) == 3
    cache.names({2, 3, 4})  # all still cached
    cache.names({1})  # evicted first, so fetched again
    assert source.calls == [{1}, {2}, {3}, {4}, {1}]


def test_expired_entries_are_dropped_from_memory(cache, clock):
    cache.names({1, 2})
    clock.now += TTL_S + 1
    cache.names({3})
    assert len(cache) == 1


@pytest.mark.parametrize(("ttl_s", "max_entries"), [(0, 10), (-1, 10), (60, 0)])
def test_nonsense_settings_are_refused(source, ttl_s, max_entries):
    with pytest.raises(ValueError):
        CachedAnimalNames(source, ttl_s=ttl_s, max_entries=max_entries)


def test_many_threads_at_once_get_consistent_answers(source):
    source.known = {i: f"Animal {i}" for i in range(1, 51)}
    cache = CachedAnimalNames(source, ttl_s=TTL_S, max_entries=20)
    start = threading.Barrier(8)
    results: list[tuple[set[int], dict[int, str]]] = []

    def load(offset: int) -> None:
        start.wait()
        for i in range(20):
            ids = {(offset + i) % 50 + 1, (offset * 3 + i) % 50 + 1}
            results.append((ids, cache.names(ids)))

    threads = [threading.Thread(target=load, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert all(found == {i: f"Animal {i}" for i in ids} for ids, found in results)
    assert len(cache) <= 20


# --- the HTTP adapter, over real HTTP -------------------------------------------------


@pytest.fixture
def stub():
    with AnimalsStub({1, 2, 7}) as running:
        yield running


def test_names_come_in_one_request_with_distinct_sorted_ids(stub):
    names = HttpAnimalNames(stub.url, timeout_s=2).names([7, 1, 7, 999])
    assert names == {1: "Animal 1", 7: "Animal 7"}
    assert stub.requests == ["/api/animals/names?ids=1,7,999"]


def test_no_ids_means_no_request(stub):
    assert HttpAnimalNames(stub.url, timeout_s=2).names([]) == {}
    assert stub.requests == []


@pytest.mark.parametrize("mode", ["error", "teapot", "malformed"])
def test_a_bad_answer_is_unavailable(stub, mode):
    stub.mode = mode
    with pytest.raises(AnimalsUnavailable):
        HttpAnimalNames(stub.url, timeout_s=2).names([1])


def test_a_slow_answer_is_given_up_on(stub):
    # Whichever gives up first, the overall deadline or the socket's own
    # timeout, the call ends at about the deadline: that is what matters.
    stub.mode, stub.delay_s = "slow", 2.0
    started = time.monotonic()
    with pytest.raises(AnimalsUnavailable):
        HttpAnimalNames(stub.url, timeout_s=0.2).names([1])
    assert time.monotonic() - started < 1.5


def test_a_stopped_animals_service_is_unavailable():
    # Refused at once on Linux ("unreachable"); on Windows a refused local
    # connection is retried past the deadline. Either way: unavailable.
    with pytest.raises(AnimalsUnavailable):
        HttpAnimalNames(f"http://127.0.0.1:{_closed_port()}", timeout_s=1).names([1])


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b'{"animals": [{"id": "1", "name": "Luna"}]}',
        b'{"animals": [{"id": true, "name": "Luna"}]}',
        b'{"animals": [{"id": 1}]}',
        b'{"animals": "everyone"}',
    ],
)
def test_a_malformed_body_is_not_trusted(monkeypatch, body):
    import donations.animals_client as client

    monkeypatch.setattr(client, "_get", lambda url, deadline: (200, body))
    with pytest.raises(AnimalsUnavailable, match="malformed"):
        HttpAnimalNames("http://animals", timeout_s=1).names([1])


# --- the staff list ---------------------------------------------------------------------


@pytest.fixture
def page_service(repository, source, clock):  # noqa: F811 (the fixture above)
    names = CachedAnimalNames(source, ttl_s=TTL_S, max_entries=10, clock=clock)
    return DonationService(repository, FakeAnimalDirectory({1, 2, 3}), today=lambda: TODAY, names=names)


def _give(service, animal_id: int | None = None) -> None:
    body = {"amount_jod": "10", "purpose": "general"}
    if animal_id is not None:
        body["earmarked_animal_id"] = animal_id
    service.record(body)


def test_a_page_asks_once_for_its_distinct_animals_and_not_again_within_the_ttl(page_service, source):
    for animal_id in (1, 2, 1, 1, 2, None, 3, 1):
        _give(page_service, animal_id)
    page = page_service.donation_page()
    assert source.calls == [{1, 2, 3}]
    assert page.names_available
    assert {d.id: page.name_of(d) for d in page.donations if d.earmarked_animal_id} == {
        d.id: {1: "Luna", 2: "Simba", 3: "Rocky"}[d.earmarked_animal_id]
        for d in page.donations
        if d.earmarked_animal_id
    }
    page_service.donation_page()
    assert source.calls == [{1, 2, 3}]  # the second load: no call at all


def test_a_page_without_earmarks_asks_nothing(page_service, source):
    _give(page_service)
    assert page_service.donation_page().names_available
    assert source.calls == []


def test_the_list_still_loads_when_the_animals_service_is_down(page_service, source):
    _give(page_service, 1)
    source.down = True
    page = page_service.donation_page()
    assert len(page.donations) == 1
    assert not page.names_available
    assert page.name_of(page.donations[0]) is None


def test_without_a_names_client_the_list_shows_ids(repository):  # noqa: F811
    service = DonationService(repository, FakeAnimalDirectory({1}), today=lambda: TODAY)
    _give(service, 1)
    assert not service.donation_page().names_available


# --- the earmark check never uses the cache ------------------------------------------


def test_the_earmark_check_asks_live_even_with_the_cache_warm(repository, stub):  # noqa: F811
    names = CachedAnimalNames(HttpAnimalNames(stub.url, timeout_s=2), ttl_s=TTL_S, max_entries=10)
    service = DonationService(repository, HttpAnimalDirectory(stub.url, timeout_s=2), today=lambda: TODAY, names=names)
    _give(service, 7)
    service.donation_page()  # warms the cache with animal 7
    stub.requests.clear()

    _give(service, 7)
    assert stub.requests == ["/api/animals/7"]  # a live check, not the cache

    stub.mode = "error"  # the animals service breaks; the cache still knows 7
    with pytest.raises(AnimalsUnavailable):
        _give(service, 7)  # fails closed: nothing is recorded on a cached name


def test_the_cache_is_not_reachable_from_the_earmark_client():
    # Structural: the earmark adapter has no cache and no names method, so no
    # code path can answer an earmark check from cached names.
    directory = HttpAnimalDirectory("http://animals", timeout_s=1)
    assert not hasattr(directory, "names")
    assert not any(isinstance(v, CachedAnimalNames) for v in vars(directory).values())


# --- across the seam: the whole donations app against the animals stand-in ------------


@pytest.fixture
def seam_client(config, database, stub):
    """The real donations app with its real HTTP adapters and cache, pointed
    at the stand-in animals service over HTTP."""
    from dataclasses import replace

    from app import create_app

    return create_app(replace(config, animals_url=stub.url), database=database).test_client()


def test_across_the_seam_the_staff_list_shows_names_from_one_request(seam_client, stub):
    for animal_id in (7, 1, 7):
        body = {"amount_jod": "10", "purpose": "general", "earmarked_animal_id": animal_id}
        assert seam_client.post("/api/donations", json=body, headers=STAFF).status_code == 201
    stub.requests.clear()

    body = seam_client.get("/api/donations", headers=STAFF).get_json()
    assert body["animal_names"] == "ok"
    assert [d["earmarked_animal_name"] for d in body["donations"]] == ["Animal 7", "Animal 1", "Animal 7"]
    assert stub.requests == ["/api/animals/names?ids=1,7"]  # one request for the page

    seam_client.get("/api/donations", headers=STAFF)
    assert stub.requests == ["/api/animals/names?ids=1,7"]  # cached: no second request


def test_across_the_seam_the_list_survives_the_animals_service_failing(seam_client, stub):
    body = {"amount_jod": "10", "purpose": "general", "earmarked_animal_id": 7}
    seam_client.post("/api/donations", json=body, headers=STAFF)
    stub.mode = "error"
    listing = seam_client.get("/api/donations", headers=STAFF)
    assert listing.status_code == 200
    payload = listing.get_json()
    assert payload["animal_names"] == "unavailable"
    assert payload["donations"][0]["earmarked_animal_id"] == 7
    assert payload["donations"][0]["earmarked_animal_name"] is None

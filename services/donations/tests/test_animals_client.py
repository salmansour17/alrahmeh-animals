"""HttpAnimalDirectory, the donations service's only call to another service,
tested over real HTTP against a stand-in animals service (ADR-6)."""

from __future__ import annotations

import socket
import time

import pytest

from donations.animals_client import HttpAnimalDirectory
from donations.service import AnimalsUnavailable
from tests.animals_stub import AnimalsStub
from tests.test_donations_service import FakeAnimalDirectory


@pytest.fixture
def stub():
    with AnimalsStub({7}) as running:
        yield running


def test_a_known_animal_exists_and_an_unknown_one_does_not(stub):
    directory = HttpAnimalDirectory(stub.url, timeout_s=2)
    assert directory.exists(7) is True
    assert directory.exists(999) is False
    assert stub.requests == ["/api/animals/7", "/api/animals/999"]


def test_the_http_adapter_and_the_fake_answer_alike(stub):
    """Liskov: the donation service cannot tell the HTTP adapter from the fake
    its unit tests use. Both take an int and return a bool for a definite
    answer; neither raises for a missing animal."""
    for directory in (HttpAnimalDirectory(stub.url, timeout_s=2), FakeAnimalDirectory({7})):
        assert directory.exists(7) is True
        assert directory.exists(999) is False


def test_a_server_error_means_unavailable_not_missing(stub):
    """A 500 says nothing about whether the animal exists, so it must not be
    read as "no such animal" and turned into a 400 for the donor."""
    stub.mode = "error"
    with pytest.raises(AnimalsUnavailable):
        HttpAnimalDirectory(stub.url, timeout_s=2).exists(7)


def test_a_slow_animals_service_is_given_up_on_at_the_timeout(stub):
    stub.mode, stub.delay_s = "slow", 2.0
    directory = HttpAnimalDirectory(stub.url, timeout_s=0.2)

    started = time.monotonic()
    with pytest.raises(AnimalsUnavailable):
        directory.exists(7)
    assert time.monotonic() - started < 1.5


def _closed_port() -> int:
    """A local port nothing is listening on: bind, read the number, close."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_a_stopped_animals_service_is_unavailable():
    directory = HttpAnimalDirectory(f"http://127.0.0.1:{_closed_port()}", timeout_s=2)
    with pytest.raises(AnimalsUnavailable):
        directory.exists(7)


def test_the_id_is_sent_as_a_number_only(stub):
    """The id comes from a donor's form. int() makes sure nothing but digits
    ever reaches the URL path."""
    HttpAnimalDirectory(stub.url + "/", timeout_s=2).exists(True)
    assert stub.requests == ["/api/animals/1"]


def test_a_slow_name_lookup_cannot_stretch_the_deadline(monkeypatch):
    """The bug this guards against: urllib's timeout covers connecting and
    reading, not looking up the host name, so a lookup that hung for seconds
    used to add its whole time on top. Now one deadline covers everything."""

    def slow_lookup(*args, **kwargs):
        time.sleep(3)
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", slow_lookup)
    directory = HttpAnimalDirectory("http://animals.invalid:8000", timeout_s=0.3)

    started = time.monotonic()
    with pytest.raises(AnimalsUnavailable, match="deadline"):
        directory.exists(7)
    assert time.monotonic() - started < 1.0


def test_an_unknown_host_is_unavailable_not_missing(monkeypatch):
    """A name that does not resolve says nothing about the animal."""

    def no_such_host(*args, **kwargs):
        raise socket.gaierror("name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", no_such_host)
    with pytest.raises(AnimalsUnavailable, match="unreachable"):
        HttpAnimalDirectory("http://animals.invalid:8000", timeout_s=2).exists(7)


def test_a_call_that_starts_after_its_deadline_is_not_sent(stub):
    from donations.animals_client import _get

    with pytest.raises(AnimalsUnavailable, match="no time left"):
        _get(f"{stub.url}/api/animals/7", deadline=time.monotonic() - 1)
    assert stub.requests == []


def test_an_unexpected_status_means_unavailable(stub):
    """Only 200 and 404 are answers about the animal; a redirect or any other
    status is treated like an error."""
    stub.mode = "teapot"
    with pytest.raises(AnimalsUnavailable, match="418"):
        HttpAnimalDirectory(stub.url, timeout_s=2).exists(7)

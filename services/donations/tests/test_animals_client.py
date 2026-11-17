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

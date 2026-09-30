"""Tests for the animal domain's business rules.

The service runs against a real SqliteAnimalRepository on a temporary database
(the `database` fixture in conftest), not a hand-written fake. That exercises
the repository's SQL and the service's rules together, and there is no fake
whose behaviour could quietly drift from the real one.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import re
from itertools import product

import pytest

from domains.animals.models import (
    MedicalRecordType,
    NewAnimal,
    PlacementStatus,
    ValidationError,
)
from domains.animals.repository import SqliteAnimalRepository
from domains.animals.service import (
    ALLOWED_TRANSITIONS,
    AnimalNotFound,
    AnimalService,
    IllegalTransition,
    TransitionConflict,
)

S = PlacementStatus
TODAY = date(2026, 9, 29)

# The confirmed lifecycle, written out independently of ALLOWED_TRANSITIONS so
# a wrong edit to the table fails a test instead of silently redefining it.
LEGAL = {
    (S.AVAILABLE, S.FOSTERING),
    (S.AVAILABLE, S.PENDING),
    (S.FOSTERING, S.AVAILABLE),
    (S.FOSTERING, S.PENDING),
    (S.PENDING, S.AVAILABLE),
    (S.PENDING, S.ADOPTED),
}
ALL_PAIRS = list(product(S, S))  # 4 x 4 = 16

# The legal route from a freshly admitted (available) animal to each status.
ROUTE_TO = {
    S.AVAILABLE: [],
    S.FOSTERING: [S.FOSTERING],
    S.PENDING: [S.PENDING],
    S.ADOPTED: [S.PENDING, S.ADOPTED],
}

VALID_ANIMAL = {
    "name": "Zaytoon",
    "species": "Dog",
    "breed": "Canaan Dog",
    "intake_date": "2026-09-01",
    "notes": "Found near Wadi Musa, underweight.",
}


@pytest.fixture
def repository(database) -> SqliteAnimalRepository:
    return SqliteAnimalRepository(database)


@pytest.fixture
def service(repository) -> AnimalService:
    return AnimalService(repository, today=lambda: TODAY)


def _animal_in(service: AnimalService, status: PlacementStatus) -> int:
    animal = service.admit(VALID_ANIMAL)
    for step in ROUTE_TO[status]:
        service.transition(animal.id, {"to": step.value})
    assert service.get(animal.id).status is status
    return animal.id


# --- transitions -------------------------------------------------------------


def test_the_table_matches_the_confirmed_lifecycle():
    table_pairs = {(a, b) for a, targets in ALLOWED_TRANSITIONS.items() for b in targets}
    assert table_pairs == LEGAL
    assert ALLOWED_TRANSITIONS[S.ADOPTED] == frozenset()


@pytest.mark.parametrize(("current", "requested"), ALL_PAIRS, ids=lambda s: s.value)
def test_every_transition_pair(service, current, requested):
    animal_id = _animal_in(service, current)

    if (current, requested) in LEGAL:
        moved = service.transition(animal_id, {"to": requested.value})
        assert moved.status is requested
    else:
        with pytest.raises(IllegalTransition) as raised:
            service.transition(animal_id, {"to": requested.value})
        # The message names both states, so staff can see what they tried.
        assert current.value in str(raised.value)
        assert requested.value in str(raised.value)
        assert service.get(animal_id).status is current


def test_transition_is_recorded_in_history_with_reason(service):
    animal_id = _animal_in(service, S.AVAILABLE)
    service.transition(animal_id, {"to": "fostering", "reason": "Placed with the Haddads"})
    service.transition(animal_id, {"to": "available", "reason": "Foster moved abroad"})

    history = service.status_history(animal_id)

    assert [(c.from_status, c.to_status) for c in history] == [
        (S.AVAILABLE, S.FOSTERING),
        (S.FOSTERING, S.AVAILABLE),
    ]
    assert history[1].reason == "Foster moved abroad"


def test_rejected_transition_writes_no_history(service):
    animal_id = _animal_in(service, S.AVAILABLE)
    with pytest.raises(IllegalTransition):
        service.transition(animal_id, {"to": "adopted"})
    assert service.status_history(animal_id) == []


def test_stale_status_loses_the_race(repository):
    """The UPDATE only matches if the status is still what the caller read.
    The second of two concurrent staff actions must change nothing."""
    animal = repository.add(_new_animal())
    assert repository.change_status(animal.id, S.AVAILABLE, S.FOSTERING, None) is True
    assert repository.change_status(animal.id, S.AVAILABLE, S.PENDING, None) is False
    assert repository.get(animal.id).status is S.FOSTERING
    assert len(repository.status_history(animal.id)) == 1


def test_service_reports_a_lost_race_as_a_conflict(repository):
    """Simulate a second member of staff moving the animal between this
    service reading it and writing it."""

    class StaleRead:
        """Serves the status the animal had before the other staff member
        acted; every other call goes to the real repository."""

        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def get(self, animal_id):
            return replace(self._real.get(animal_id), status=S.AVAILABLE)

    animal = repository.add(_new_animal())
    repository.change_status(animal.id, S.AVAILABLE, S.FOSTERING, None)  # the other click

    service = AnimalService(StaleRead(repository), today=lambda: TODAY)
    with pytest.raises(TransitionConflict):
        service.transition(animal.id, {"to": "pending"})
    assert repository.get(animal.id).status is S.FOSTERING


# --- admission and validation ------------------------------------------------


def test_admitted_animal_starts_available_and_round_trips(service):
    animal = service.admit(VALID_ANIMAL)

    assert animal.status is S.AVAILABLE
    assert service.get(animal.id) == animal
    assert animal.intake_date == date(2026, 9, 1)


def test_text_is_trimmed_and_blank_optionals_become_none(service):
    animal = service.admit({**VALID_ANIMAL, "name": "  Zaytoon  ", "breed": "", "notes": None})
    assert animal.name == "Zaytoon"
    assert animal.breed is None
    assert animal.notes is None


def test_intake_today_is_allowed(service):
    assert service.admit({**VALID_ANIMAL, "intake_date": TODAY.isoformat()}).intake_date == TODAY


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        (None, "JSON object"),
        (["Zaytoon"], "JSON object"),
        ({k: v for k, v in VALID_ANIMAL.items() if k != "name"}, "missing field(s): name"),
        ({**VALID_ANIMAL, "status": "adopted"}, "unknown field(s): status"),
        ({**VALID_ANIMAL, "name": "   "}, "name must be a non-empty string"),
        ({**VALID_ANIMAL, "name": 42}, "name must be a non-empty string"),
        ({**VALID_ANIMAL, "name": "x" * 81}, "at most 80"),
        ({**VALID_ANIMAL, "notes": "x" * 2001}, "at most 2000"),
        ({**VALID_ANIMAL, "intake_date": "01/09/2026"}, "ISO date"),
        ({**VALID_ANIMAL, "intake_date": 20260901}, "ISO date"),
        ({**VALID_ANIMAL, "intake_date": "2026-09-30"}, "future"),
    ],
)
def test_invalid_animal_is_rejected(service, payload, complaint):
    with pytest.raises(ValidationError, match=_literal(complaint)):
        service.admit(payload)
    assert service.list_animals() == []


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        ({}, "missing field(s): to"),
        ({"to": "sold"}, "to must be one of"),
        ({"to": ["pending"]}, "to must be one of"),
        ({"to": "pending", "by": "Salma"}, "unknown field(s): by"),
        ({"to": "pending", "reason": "x" * 501}, "at most 500"),
    ],
)
def test_invalid_transition_request_is_rejected(service, payload, complaint):
    animal_id = _animal_in(service, S.AVAILABLE)
    with pytest.raises(ValidationError, match=_literal(complaint)):
        service.transition(animal_id, payload)


# --- listing -----------------------------------------------------------------


def test_list_filters_by_status(service):
    available = _animal_in(service, S.AVAILABLE)
    fostering = _animal_in(service, S.FOSTERING)

    assert [a.id for a in service.list_animals()] == [available, fostering]
    assert [a.id for a in service.list_animals("fostering")] == [fostering]
    assert service.list_animals("adopted") == []


def test_list_rejects_unknown_status_filter(service):
    with pytest.raises(ValidationError, match="status must be one of"):
        service.list_animals("lost")


# --- not found ---------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda s: s.get(999),
        lambda s: s.transition(999, {"to": "pending"}),
        lambda s: s.status_history(999),
        lambda s: s.medical_history(999),
        lambda s: s.vaccinations(999),
        lambda s: s.record_medical(
            999, {"record_type": "checkup", "description": "x", "occurred_on": "2026-09-01"}
        ),
    ],
    ids=["get", "transition", "history", "medical", "vaccinations", "record_medical"],
)
def test_unknown_animal_raises_not_found(service, call):
    with pytest.raises(AnimalNotFound, match="999"):
        call(service)


# --- medical records ---------------------------------------------------------


def test_vaccinations_are_the_public_subset_of_medical_history(service):
    animal_id = _animal_in(service, S.AVAILABLE)
    service.record_medical(
        animal_id,
        {"record_type": "vaccination", "description": "Rabies", "occurred_on": "2026-09-10"},
    )
    service.record_medical(
        animal_id,
        {"record_type": "treatment", "description": "Tick fever, doxycycline", "occurred_on": "2026-09-05"},
    )

    full = service.medical_history(animal_id)
    public = service.vaccinations(animal_id)

    # Full history is in date order, not insertion order.
    assert [r.record_type for r in full] == [MedicalRecordType.TREATMENT, MedicalRecordType.VACCINATION]
    assert [r.description for r in public] == ["Rabies"]


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        ({"record_type": "surgery", "description": "x", "occurred_on": "2026-09-01"}, "record_type must be one of"),
        ({"record_type": "checkup", "description": "", "occurred_on": "2026-09-01"}, "non-empty"),
        ({"record_type": "checkup", "description": "x", "occurred_on": "2027-01-01"}, "future"),
        ({"record_type": "checkup", "description": "x"}, "missing field(s): occurred_on"),
    ],
)
def test_invalid_medical_record_is_rejected(service, payload, complaint):
    animal_id = _animal_in(service, S.AVAILABLE)
    with pytest.raises(ValidationError, match=_literal(complaint)):
        service.record_medical(animal_id, payload)
    assert service.medical_history(animal_id) == []


# --- helpers -----------------------------------------------------------------


def _new_animal() -> NewAnimal:
    return NewAnimal.from_payload(VALID_ANIMAL, TODAY)


def _literal(text: str) -> str:
    return re.escape(text)


# --- placement counts --------------------------------------------------------


def test_placement_counts_include_every_status_even_when_zero(service):
    assert service.placement_counts() == {status: 0 for status in S}

    _animal_in(service, S.AVAILABLE)
    _animal_in(service, S.ADOPTED)
    _animal_in(service, S.ADOPTED)

    assert service.placement_counts() == {
        S.AVAILABLE: 1,
        S.FOSTERING: 0,
        S.PENDING: 0,
        S.ADOPTED: 2,
    }

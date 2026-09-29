"""Business rules for animal intake and placement.

The service depends on the AnimalRepository Protocol below, never on SQLite.
create_app() decides which concrete repository to hand it; tests hand it one
built on a temporary database. That is the dependency inversion: the rules sit
above the storage, and the storage conforms to an interface the rules define.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Protocol

from domains.animals.models import (
    Animal,
    MedicalRecord,
    MedicalRecordType,
    NewAnimal,
    NewMedicalRecord,
    PlacementStatus,
    StatusChange,
    TransitionRequest,
    parse_status,
)

# The whole placement lifecycle as data. Adding a state or a move means editing
# this table, not threading a new branch through an if/elif chain. A status
# missing from the right-hand side of every entry is unreachable; one with an
# empty set is terminal.
ALLOWED_TRANSITIONS: dict[PlacementStatus, frozenset[PlacementStatus]] = {
    PlacementStatus.AVAILABLE: frozenset({PlacementStatus.FOSTERING, PlacementStatus.PENDING}),
    # A foster can hand the animal back, or apply to adopt it themselves.
    PlacementStatus.FOSTERING: frozenset({PlacementStatus.AVAILABLE, PlacementStatus.PENDING}),
    # An application is either withdrawn/declined or finalised.
    PlacementStatus.PENDING: frozenset({PlacementStatus.AVAILABLE, PlacementStatus.ADOPTED}),
    PlacementStatus.ADOPTED: frozenset(),
}


class AnimalNotFound(LookupError):
    def __init__(self, animal_id: int) -> None:
        super().__init__(f"no animal with id {animal_id}")


class IllegalTransition(ValueError):
    """The lifecycle does not allow this move at all."""

    def __init__(self, current: PlacementStatus, requested: PlacementStatus) -> None:
        super().__init__(f"cannot move an animal from {current.value} to {requested.value}")


class TransitionConflict(RuntimeError):
    """The move was legal, but someone else changed the status first."""

    def __init__(self, animal_id: int, expected: PlacementStatus) -> None:
        super().__init__(
            f"animal {animal_id} is no longer {expected.value}; reload and try again"
        )


class AnimalRepository(Protocol):
    """What the service needs from storage, and nothing more."""

    def add(self, animal: NewAnimal) -> Animal: ...

    def get(self, animal_id: int) -> Animal | None: ...

    def list(self, status: PlacementStatus | None) -> list[Animal]: ...

    def change_status(
        self, animal_id: int, expected: PlacementStatus, new: PlacementStatus, reason: str | None
    ) -> bool: ...

    def status_history(self, animal_id: int) -> list[StatusChange]: ...

    def add_medical_record(self, animal_id: int, record: NewMedicalRecord) -> MedicalRecord: ...

    def medical_records(
        self, animal_id: int, record_type: MedicalRecordType | None
    ) -> list[MedicalRecord]: ...


def check_transition(current: PlacementStatus, requested: PlacementStatus) -> None:
    """Raise IllegalTransition unless the lifecycle allows current → requested.
    A same-state move is never in the table, so it is rejected too."""
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise IllegalTransition(current, requested)


class AnimalService:
    def __init__(
        self, repository: AnimalRepository, today: Callable[[], date] = date.today
    ) -> None:
        # `today` is injected so tests can pin the date that "no intake date in
        # the future" is checked against, instead of depending on the clock.
        self._repository = repository
        self._today = today

    def admit(self, payload: Any) -> Animal:
        return self._repository.add(NewAnimal.from_payload(payload, self._today()))

    def list_animals(self, status: str | None = None) -> list[Animal]:
        return self._repository.list(parse_status(status))

    def get(self, animal_id: int) -> Animal:
        animal = self._repository.get(animal_id)
        if animal is None:
            raise AnimalNotFound(animal_id)
        return animal

    def transition(self, animal_id: int, payload: Any) -> Animal:
        request = TransitionRequest.from_payload(payload)
        animal = self.get(animal_id)
        check_transition(animal.status, request.to)
        if not self._repository.change_status(animal_id, animal.status, request.to, request.reason):
            raise TransitionConflict(animal_id, animal.status)
        return self.get(animal_id)

    def status_history(self, animal_id: int) -> list[StatusChange]:
        self.get(animal_id)
        return self._repository.status_history(animal_id)

    def record_medical(self, animal_id: int, payload: Any) -> MedicalRecord:
        record = NewMedicalRecord.from_payload(payload, self._today())
        self.get(animal_id)
        return self._repository.add_medical_record(animal_id, record)

    def medical_history(self, animal_id: int) -> list[MedicalRecord]:
        """Every record. Staff-only: treatment notes are internal."""
        self.get(animal_id)
        return self._repository.medical_records(animal_id, None)

    def vaccinations(self, animal_id: int) -> list[MedicalRecord]:
        """The public subset of the medical history: what an adopter needs."""
        self.get(animal_id)
        return self._repository.medical_records(animal_id, MedicalRecordType.VACCINATION)

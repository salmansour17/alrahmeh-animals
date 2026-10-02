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
    Decision,
    MedicalRecord,
    MedicalRecordType,
    NewAnimal,
    NewMedicalRecord,
    NewPlacementRequest,
    PlacementRequest,
    PlacementStatus,
    RequestKind,
    RequestOutcome,
    StatusChange,
    StatusMove,
    TransitionRequest,
    ValidationError,
    is_honeypot,
    parse_outcome,
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


# Which requests an animal can receive, by its status. A pending animal still
# takes adoption requests, as backups in case the approved one falls through.
ACCEPTS_REQUESTS: dict[PlacementStatus, frozenset[RequestKind]] = {
    PlacementStatus.AVAILABLE: frozenset({RequestKind.ADOPTION, RequestKind.FOSTER}),
    PlacementStatus.FOSTERING: frozenset({RequestKind.ADOPTION}),
    PlacementStatus.PENDING: frozenset({RequestKind.ADOPTION}),
    PlacementStatus.ADOPTED: frozenset(),
}

# Approving a request moves the animal here, always through check_transition.
APPROVAL_MOVES_TO: dict[RequestKind, PlacementStatus] = {
    RequestKind.ADOPTION: PlacementStatus.PENDING,
    RequestKind.FOSTER: PlacementStatus.FOSTERING,
}

# Approving a request of this kind declines the other open requests of these
# kinds for the same animal. One foster family at a time; adoption requests are
# left open as backups.
APPROVAL_DECLINES_OPEN: dict[RequestKind, frozenset[RequestKind]] = {
    RequestKind.ADOPTION: frozenset(),
    RequestKind.FOSTER: frozenset({RequestKind.FOSTER}),
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


class RequestNotFound(LookupError):
    def __init__(self, request_id: int) -> None:
        super().__init__(f"no request with id {request_id}")


class RequestNotAccepted(RuntimeError):
    """The animal's status rules out this kind of request."""

    def __init__(self, animal: Animal, kind: RequestKind) -> None:
        super().__init__(f"{animal.name} is {animal.status.value} and cannot take {kind.value} requests")


class RequestAlreadyDecided(RuntimeError):
    def __init__(self, request: PlacementRequest) -> None:
        super().__init__(f"request {request.id} is already {request.outcome.value}")


class AdoptionAlreadyApproved(RuntimeError):
    """At most one adoption is approved at a time."""

    def __init__(self, animal: Animal) -> None:
        super().__init__(
            f"{animal.name} already has an approved adoption; decline it or complete it first"
        )


class RequestConflict(RuntimeError):
    """Someone else changed the request or the animal first."""

    def __init__(self, request_id: int) -> None:
        super().__init__(f"request {request_id} or its animal changed meanwhile; reload and try again")


class InvalidPhoto(ValidationError):
    """An upload that is not a usable image of the type it claims to be."""


class UnsupportedPhotoType(ValueError):
    def __init__(self, content_type: str) -> None:
        super().__init__("send the photo as image/jpeg, image/png or image/webp")
        self.content_type = content_type


class PhotoNotFound(LookupError):
    def __init__(self, animal_id: int) -> None:
        super().__init__(f"no photo for animal {animal_id}")


class PhotoStore(Protocol):
    """Where animal photos are kept. The service never touches files itself."""

    def save(self, animal_id: int, photo: bytes) -> None: ...

    def load(self, animal_id: int) -> bytes | None: ...

    def version(self, animal_id: int) -> int | None: ...


class AnimalRepository(Protocol):
    """What the service needs from storage, and nothing more."""

    def add(self, animal: NewAnimal) -> Animal: ...

    def get(self, animal_id: int) -> Animal | None: ...

    def list(self, status: PlacementStatus | None) -> list[Animal]: ...

    def count_by_status(self) -> dict[PlacementStatus, int]: ...

    def change_status(
        self,
        animal_id: int,
        expected: PlacementStatus,
        new: PlacementStatus,
        reason: str | None,
        close_open_requests: bool = False,
    ) -> bool: ...

    def status_history(self, animal_id: int) -> list[StatusChange]: ...

    def add_medical_record(self, animal_id: int, record: NewMedicalRecord) -> MedicalRecord: ...

    def medical_records(
        self, animal_id: int, record_type: MedicalRecordType | None
    ) -> list[MedicalRecord]: ...


class PlacementRepository(Protocol):
    """What PlacementService needs from storage."""

    def add_request(self, animal_id: int, request: NewPlacementRequest) -> PlacementRequest: ...

    def get_request(self, request_id: int) -> PlacementRequest | None: ...

    def list_requests(self, outcome: RequestOutcome | None) -> list[PlacementRequest]: ...

    def decide(
        self,
        request_id: int,
        expected: RequestOutcome,
        new: RequestOutcome,
        move: StatusMove | None,
        decline_open: frozenset[RequestKind],
    ) -> bool: ...


def check_transition(current: PlacementStatus, requested: PlacementStatus) -> None:
    """Raise IllegalTransition unless the lifecycle allows current → requested.
    A same-state move is never in the table, so it is rejected too."""
    if requested not in ALLOWED_TRANSITIONS[current]:
        raise IllegalTransition(current, requested)


class AnimalService:
    def __init__(self, repository: AnimalRepository, today: Callable[[], date]) -> None:
        # `today` is injected, with no default, so the caller decides which
        # calendar it is (create_app passes Amman's) and tests can pin it.
        self._repository = repository
        self._today = today

    def admit(self, payload: Any) -> Animal:
        return self._repository.add(NewAnimal.from_payload(payload, self._today()))

    def list_animals(self, status: str | None = None) -> list[Animal]:
        return self._repository.list(parse_status(status))

    def placement_counts(self) -> dict[PlacementStatus, int]:
        """Animals per status, every status present. The homepage's "found
        homes" figure is the ADOPTED count, read live rather than typed in."""
        counts = self._repository.count_by_status()
        return {status: counts.get(status, 0) for status in PlacementStatus}

    def get(self, animal_id: int) -> Animal:
        animal = self._repository.get(animal_id)
        if animal is None:
            raise AnimalNotFound(animal_id)
        return animal

    def transition(self, animal_id: int, payload: Any) -> Animal:
        request = TransitionRequest.from_payload(payload)
        animal = self.get(animal_id)
        check_transition(animal.status, request.to)
        # Once an animal is adopted, nobody else's request can still be open.
        adopted = request.to is PlacementStatus.ADOPTED
        if not self._repository.change_status(
            animal_id, animal.status, request.to, request.reason, close_open_requests=adopted
        ):
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


class PlacementService:
    """Adoption and foster requests: the public asks, staff decide.

    Kept apart from AnimalService so neither grows into a god class. It reads
    animals through AnimalService, and every status change it causes goes
    through the same check_transition table as a staff transition.
    """

    def __init__(self, repository: PlacementRepository, animals: AnimalService) -> None:
        self._repository = repository
        self._animals = animals

    def submit(self, animal_id: int, payload: Any) -> PlacementRequest | None:
        """Record a request from the public. Returns None for a honeypot hit,
        which the caller answers exactly like a real request."""
        if is_honeypot(payload):
            return None
        request = NewPlacementRequest.from_payload(payload)
        animal = self._animals.get(animal_id)
        if request.kind not in ACCEPTS_REQUESTS[animal.status]:
            raise RequestNotAccepted(animal, request.kind)
        return self._repository.add_request(animal_id, request)

    def list_requests(self, status: str | None = None) -> list[PlacementRequest]:
        return self._repository.list_requests(parse_outcome(status))

    def decide(self, request_id: int, payload: Any) -> PlacementRequest:
        decision = Decision.from_payload(payload)
        request = self._get(request_id)
        animal = self._animals.get(request.animal_id)

        if decision.outcome is RequestOutcome.APPROVED:
            expected, move, decline = self._approval(request, animal, decision)
        else:
            expected, move, decline = self._declining(request, animal, decision)

        if not self._repository.decide(request_id, expected, decision.outcome, move, decline):
            raise RequestConflict(request_id)
        return self._get(request_id)

    def _approval(
        self, request: PlacementRequest, animal: Animal, decision: Decision
    ) -> tuple[RequestOutcome, StatusMove | None, frozenset[RequestKind]]:
        if request.outcome is not RequestOutcome.OPEN:
            raise RequestAlreadyDecided(request)
        if request.kind is RequestKind.ADOPTION and animal.status is PlacementStatus.PENDING:
            raise AdoptionAlreadyApproved(animal)
        target = APPROVAL_MOVES_TO[request.kind]
        check_transition(animal.status, target)
        reason = decision.reason or f"{request.kind.value} request {request.id} approved"
        move = StatusMove(animal.id, animal.status, target, reason)
        return RequestOutcome.OPEN, move, APPROVAL_DECLINES_OPEN[request.kind]

    def _declining(
        self, request: PlacementRequest, animal: Animal, decision: Decision
    ) -> tuple[RequestOutcome, StatusMove | None, frozenset[RequestKind]]:
        # An open request: only the request changes.
        if request.outcome is RequestOutcome.OPEN:
            return RequestOutcome.OPEN, None, frozenset()
        # The approved adoption fell through: the animal is available again,
        # and any backup requests stay open for staff to approve next.
        is_live_adoption = (
            request.outcome is RequestOutcome.APPROVED
            and request.kind is RequestKind.ADOPTION
            and animal.status is PlacementStatus.PENDING
        )
        if not is_live_adoption:
            raise RequestAlreadyDecided(request)
        check_transition(animal.status, PlacementStatus.AVAILABLE)
        reason = decision.reason or f"adoption request {request.id} fell through"
        move = StatusMove(animal.id, animal.status, PlacementStatus.AVAILABLE, reason)
        return RequestOutcome.APPROVED, move, frozenset()

    def _get(self, request_id: int) -> PlacementRequest:
        request = self._repository.get_request(request_id)
        if request is None:
            raise RequestNotFound(request_id)
        return request


class PhotoService:
    """One photo per animal: staff upload, the public views.

    Turning an upload into a safe image is someone else's job: `prepare` is
    injected by create_app (domains/animals/photos.py), so this class never
    imports an image library and tests can pass a trivial stand-in.
    """

    def __init__(
        self,
        animals: AnimalService,
        store: PhotoStore,
        prepare: Callable[[bytes, str], bytes],
    ) -> None:
        self._animals = animals
        self._store = store
        self._prepare = prepare

    def upload(self, animal_id: int, data: bytes, content_type: str) -> str:
        """Store a new photo for an animal and return its public address."""
        self._animals.get(animal_id)
        self._store.save(animal_id, self._prepare(data, content_type))
        return self.photo_url(animal_id)

    def photo(self, animal_id: int) -> bytes:
        self._animals.get(animal_id)
        photo = self._store.load(animal_id)
        if photo is None:
            raise PhotoNotFound(animal_id)
        return photo

    def version(self, animal_id: int) -> int | None:
        return self._store.version(animal_id)

    def photo_url(self, animal_id: int) -> str | None:
        """The photo's address, with its version, so a replaced photo is never
        served from a browser's cache. None when there is no photo yet."""
        version = self._store.version(animal_id)
        if version is None:
            return None
        return f"/api/animals/{animal_id}/photo?v={version}"


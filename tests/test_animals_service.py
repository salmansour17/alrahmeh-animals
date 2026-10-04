"""Tests for the animal domain's business rules.

The service runs against a real SqliteAnimalRepository on a temporary database
(the `database` fixture in conftest), not a hand-written fake. That exercises
the repository's SQL and the service's rules together, and there is no fake
whose behaviour could quietly drift from the real one.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
import re
from io import BytesIO
from itertools import product

import pytest
from PIL import ExifTags, Image

from db.connection import SCHEMA_PATH
from domains.animals.models import (
    AnimalProfile,
    MedicalRecordType,
    age_text,
    weight_text,
    NewAnimal,
    NewPlacementRequest,
    PlacementStatus,
    RequestKind,
    RequestOutcome,
    StatusMove,
    ValidationError,
)
from domains.animals.photos import (
    MAX_DECODED_PIXELS,
    MAX_PHOTO_SIDE,
    FileSystemPhotoStore,
    prepare_photo,
)
from domains.animals.repository import SqliteAnimalRepository, SqlitePlacementRepository
from domains.animals.service import (
    ALLOWED_TRANSITIONS,
    AdoptionAlreadyApproved,
    AnimalNotFound,
    AnimalService,
    IllegalTransition,
    InvalidPhoto,
    PhotoNotFound,
    PhotoService,
    PlacementService,
    RequestAlreadyDecided,
    RequestConflict,
    RequestNotAccepted,
    RequestNotFound,
    TransitionConflict,
    UnsupportedPhotoType,
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


# --- adoption and foster requests --------------------------------------------

K = RequestKind
APPLICANT = {"name": "Rana Haddad", "email": "rana@example.org", "message": "We have a garden."}


@pytest.fixture
def placement_repository(database) -> SqlitePlacementRepository:
    return SqlitePlacementRepository(database)


@pytest.fixture
def placements(placement_repository, service) -> PlacementService:
    return PlacementService(placement_repository, service)


def _ask(placements, animal_id, kind=K.ADOPTION, **extra):
    return placements.submit(animal_id, {"kind": kind.value, **APPLICANT, **extra})


def _request_in(placement_repository, animal_id, kind) -> int:
    """A request created directly, bypassing the who-may-ask rules, so a
    decision can be tested against every animal status."""
    return placement_repository.add_request(
        animal_id, NewPlacementRequest.from_payload({"kind": kind.value, **APPLICANT})
    ).id


def _outcome(placement_repository, request_id) -> RequestOutcome:
    return placement_repository.get_request(request_id).outcome


def test_request_enums_match_the_schema_check_constraints():
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    for column, enum in (("kind", RequestKind), ("outcome", RequestOutcome)):
        allowed = re.search(rf"CHECK \({column} IN \(([^)]*)\)\)", schema).group(1)
        assert {v.strip().strip("'") for v in allowed.split(",")} == {e.value for e in enum}


ACCEPTED = {
    (K.ADOPTION, S.AVAILABLE),
    (K.FOSTER, S.AVAILABLE),
    (K.ADOPTION, S.FOSTERING),
    (K.ADOPTION, S.PENDING),
}


@pytest.mark.parametrize(("kind", "status"), list(product(K, S)), ids=lambda v: v.value)
def test_who_may_ask_for_what(service, placements, kind, status):
    animal_id = _animal_in(service, status)
    if (kind, status) in ACCEPTED:
        request = _ask(placements, animal_id, kind)
        assert request.outcome is RequestOutcome.OPEN
        assert service.get(animal_id).status is status  # asking never moves an animal
    else:
        with pytest.raises(RequestNotAccepted):
            _ask(placements, animal_id, kind)


# What approving a request does, for every kind and starting status.
APPROVE = {
    (K.ADOPTION, S.AVAILABLE): S.PENDING,
    (K.ADOPTION, S.FOSTERING): S.PENDING,
    (K.ADOPTION, S.PENDING): AdoptionAlreadyApproved,
    (K.ADOPTION, S.ADOPTED): IllegalTransition,
    (K.FOSTER, S.AVAILABLE): S.FOSTERING,
    (K.FOSTER, S.FOSTERING): IllegalTransition,
    (K.FOSTER, S.PENDING): IllegalTransition,
    (K.FOSTER, S.ADOPTED): IllegalTransition,
}


@pytest.mark.parametrize(("kind", "status"), list(product(K, S)), ids=lambda v: v.value)
def test_approving_every_kind_from_every_status(service, placements, placement_repository, kind, status):
    animal_id = _animal_in(service, status)
    request_id = _request_in(placement_repository, animal_id, kind)
    expected = APPROVE[(kind, status)]

    if isinstance(expected, PlacementStatus):
        decided = placements.decide(request_id, {"outcome": "approved"})
        assert decided.outcome is RequestOutcome.APPROVED
        assert service.get(animal_id).status is expected
        assert service.status_history(animal_id)[-1].reason == f"{kind.value} request {request_id} approved"
    else:
        with pytest.raises(expected):
            placements.decide(request_id, {"outcome": "approved"})
        assert service.get(animal_id).status is status
        assert _outcome(placement_repository, request_id) is RequestOutcome.OPEN


def test_a_decided_request_cannot_be_approved_again(service, placements):
    request = _ask(placements, _animal_in(service, S.AVAILABLE))
    placements.decide(request.id, {"outcome": "declined"})
    with pytest.raises(RequestAlreadyDecided):
        placements.decide(request.id, {"outcome": "approved"})


def test_declining_an_open_request_changes_only_the_request(service, placements):
    animal_id = _animal_in(service, S.AVAILABLE)
    chosen, backup = _ask(placements, animal_id), _ask(placements, animal_id)
    placements.decide(chosen.id, {"outcome": "approved"})

    placements.decide(backup.id, {"outcome": "declined"})

    # Declining a backup must not undo the adoption that is going ahead.
    assert service.get(animal_id).status is S.PENDING


def test_when_the_approved_adoption_falls_through_the_next_can_be_approved(
    service, placements, placement_repository
):
    animal_id = _animal_in(service, S.AVAILABLE)
    first, backup = _ask(placements, animal_id), _ask(placements, animal_id)
    placements.decide(first.id, {"outcome": "approved"})

    placements.decide(first.id, {"outcome": "declined", "reason": "Family moved abroad"})

    assert service.get(animal_id).status is S.AVAILABLE
    assert service.status_history(animal_id)[-1].reason == "Family moved abroad"
    assert _outcome(placement_repository, backup.id) is RequestOutcome.OPEN
    placements.decide(backup.id, {"outcome": "approved"})
    assert service.get(animal_id).status is S.PENDING


def test_moving_a_pending_animal_back_by_hand_declines_its_approved_adoption(
    service, placements, placement_repository
):
    animal_id = _animal_in(service, S.AVAILABLE)
    first, backup = _ask(placements, animal_id), _ask(placements, animal_id)
    placements.decide(first.id, {"outcome": "approved"})

    service.transition(animal_id, {"to": "available", "reason": "Fell through"})

    # Same result as declining it: the approval ends, the backup stays open,
    # and the backup can then be approved without two approvals coexisting.
    assert _outcome(placement_repository, first.id) is RequestOutcome.DECLINED
    assert _outcome(placement_repository, backup.id) is RequestOutcome.OPEN
    placements.decide(backup.id, {"outcome": "approved"})
    approved = placements.list_requests("approved")
    assert [request.id for request in approved] == [backup.id]
    assert service.get(animal_id).status is S.PENDING


def test_an_approved_foster_cannot_be_declined(service, placements):
    request = _ask(placements, _animal_in(service, S.AVAILABLE), K.FOSTER)
    placements.decide(request.id, {"outcome": "approved"})
    with pytest.raises(RequestAlreadyDecided):
        placements.decide(request.id, {"outcome": "declined"})


def test_a_declined_request_cannot_be_declined_again(service, placements):
    request = _ask(placements, _animal_in(service, S.AVAILABLE))
    placements.decide(request.id, {"outcome": "declined"})
    with pytest.raises(RequestAlreadyDecided):
        placements.decide(request.id, {"outcome": "declined"})


def test_approving_a_foster_declines_other_foster_requests_but_not_adoptions(
    service, placements, placement_repository
):
    animal_id = _animal_in(service, S.AVAILABLE)
    chosen = _ask(placements, animal_id, K.FOSTER)
    other_foster = _ask(placements, animal_id, K.FOSTER)
    adoption = _ask(placements, animal_id, K.ADOPTION)

    placements.decide(chosen.id, {"outcome": "approved"})

    assert service.get(animal_id).status is S.FOSTERING
    assert _outcome(placement_repository, other_foster.id) is RequestOutcome.DECLINED
    assert _outcome(placement_repository, adoption.id) is RequestOutcome.OPEN


def test_adoption_declines_every_remaining_open_request(service, placements, placement_repository):
    animal_id = _animal_in(service, S.AVAILABLE)
    chosen = _ask(placements, animal_id)
    foster = _ask(placements, animal_id, K.FOSTER)
    placements.decide(chosen.id, {"outcome": "approved"})
    backup = _ask(placements, animal_id)

    service.transition(animal_id, {"to": "adopted"})

    assert _outcome(placement_repository, chosen.id) is RequestOutcome.APPROVED
    assert _outcome(placement_repository, foster.id) is RequestOutcome.DECLINED
    assert _outcome(placement_repository, backup.id) is RequestOutcome.DECLINED
    assert placements.list_requests("open") == []


def test_two_staff_deciding_at_once_only_one_wins(service, placements, placement_repository):
    """The second decision was based on a stale read: the request was open
    when it looked, but the first decision landed in between."""
    request = _ask(placements, _animal_in(service, S.AVAILABLE))
    stale_view = placement_repository.get_request(request.id)

    class StaleRequests:
        def __init__(self, real):
            self._real = real

        def __getattr__(self, name):
            return getattr(self._real, name)

        def get_request(self, request_id):
            return stale_view

    placements.decide(request.id, {"outcome": "declined"})  # the first member of staff
    late = PlacementService(StaleRequests(placement_repository), service)
    with pytest.raises(RequestConflict):
        late.decide(request.id, {"outcome": "approved"})
    assert _outcome(placement_repository, request.id) is RequestOutcome.DECLINED


def test_a_failed_status_change_rolls_back_the_decision(service, placement_repository):
    """If the animal moved meanwhile, neither the decision nor the move lands."""
    animal_id = _animal_in(service, S.FOSTERING)
    request_id = _request_in(placement_repository, animal_id, K.ADOPTION)

    landed = placement_repository.decide(
        request_id,
        RequestOutcome.OPEN,
        RequestOutcome.APPROVED,
        StatusMove(animal_id, S.AVAILABLE, S.PENDING, "stale"),  # it is not available
        frozenset(),
    )

    assert landed is False
    assert _outcome(placement_repository, request_id) is RequestOutcome.OPEN
    assert service.get(animal_id).status is S.FOSTERING


def test_a_filled_honeypot_is_accepted_silently_and_stores_nothing(service, placements):
    animal_id = _animal_in(service, S.AVAILABLE)
    assert _ask(placements, animal_id, website="http://cheap-pills.example") is None
    # Even an invalid bot submission gets the same silent answer.
    assert placements.submit(animal_id, {"website": "x", "kind": "nonsense"}) is None
    assert placements.list_requests() == []


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        (None, "JSON object"),
        ({"kind": "adoption", "name": "Rana"}, "missing field(s): email"),
        ({**APPLICANT, "kind": "sponsor"}, "kind must be one of"),
        ({**APPLICANT, "kind": "adoption", "phone": "079"}, "unknown field(s): phone"),
        ({**APPLICANT, "kind": "adoption", "name": "x" * 121}, "at most 120"),
        ({**APPLICANT, "kind": "adoption", "message": "x" * 2001}, "at most 2000"),
        ({**APPLICANT, "kind": "adoption", "email": "rana.example.org"}, "must look like"),
        ({**APPLICANT, "kind": "adoption", "email": "rana@localhost"}, "must look like"),
        ({**APPLICANT, "kind": "adoption", "email": "ra na@example.org"}, "must look like"),
        ({**APPLICANT, "kind": "adoption", "email": "x" * 250 + "@a.io"}, "at most 254"),
    ],
)
def test_invalid_requests_are_rejected_without_echoing_personal_data(
    service, placements, payload, complaint
):
    animal_id = _animal_in(service, S.AVAILABLE)
    with pytest.raises(ValidationError, match=re.escape(complaint)) as raised:
        placements.submit(animal_id, payload)
    assert "rana" not in str(raised.value).lower()
    assert placements.list_requests() == []


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        ({"outcome": "open"}, "approved or declined"),
        ({"outcome": "maybe"}, "outcome must be one of"),
        ({"outcome": "approved", "by": "Salma"}, "unknown field(s): by"),
    ],
)
def test_invalid_decisions_are_rejected(service, placements, payload, complaint):
    request = _ask(placements, _animal_in(service, S.AVAILABLE))
    with pytest.raises(ValidationError, match=re.escape(complaint)):
        placements.decide(request.id, payload)


def test_requests_are_listed_and_filtered(service, placements):
    animal_id = _animal_in(service, S.AVAILABLE)
    first, second = _ask(placements, animal_id), _ask(placements, animal_id, K.FOSTER)
    placements.decide(first.id, {"outcome": "declined"})

    assert [r.id for r in placements.list_requests()] == [first.id, second.id]
    assert [r.id for r in placements.list_requests("open")] == [second.id]
    with pytest.raises(ValidationError):
        placements.list_requests("lost")


def test_unknown_request_or_animal(service, placements):
    with pytest.raises(RequestNotFound):
        placements.decide(999, {"outcome": "approved"})
    with pytest.raises(AnimalNotFound):
        _ask(placements, 999)


# --- photos ------------------------------------------------------------------

AMMAN_GPS = {
    ExifTags.GPS.GPSLatitudeRef: "N",
    ExifTags.GPS.GPSLatitude: (31.0, 57.0, 0.0),
    ExifTags.GPS.GPSLongitudeRef: "E",
    ExifTags.GPS.GPSLongitude: (35.0, 55.0, 0.0),
}


def image_bytes(fmt="JPEG", size=(64, 48), mode="RGB", gps=False, orientation=None) -> bytes:
    image = Image.new(mode, size, "orange" if mode == "RGB" else 0)
    exif = Image.Exif()
    if gps:
        exif[ExifTags.Base.GPSInfo] = AMMAN_GPS
    if orientation:
        exif[ExifTags.Base.Orientation] = orientation
    out = BytesIO()
    image.save(out, fmt, **({"exif": exif} if fmt == "JPEG" else {}))
    return out.getvalue()


def opened(data: bytes) -> Image.Image:
    return Image.open(BytesIO(data))


def test_gps_is_gone_after_an_upload_is_prepared():
    original = image_bytes(gps=True)
    assert opened(original).getexif().get_ifd(ExifTags.IFD.GPSInfo)  # it really was there

    stored = opened(prepare_photo(original, "image/jpeg"))

    assert stored.format == "WEBP"
    assert dict(stored.getexif()) == {}
    assert "exif" not in stored.info and "xmp" not in stored.info


def test_the_camera_rotation_is_applied_before_metadata_is_dropped():
    sideways = image_bytes(size=(200, 100), orientation=6)  # "rotate 90 degrees"
    assert opened(prepare_photo(sideways, "image/jpeg")).size == (100, 200)


def test_large_photos_are_capped_on_their_longest_side():
    assert opened(prepare_photo(image_bytes(size=(3200, 1000)), "image/jpeg")).size == (MAX_PHOTO_SIDE, 500)


def test_transparency_survives_and_other_types_are_accepted():
    png = image_bytes("PNG", mode="RGBA")
    assert opened(prepare_photo(png, "image/png")).mode == "RGBA"
    webp = image_bytes("WEBP")
    assert opened(prepare_photo(webp, "image/webp")).format == "WEBP"


@pytest.mark.parametrize("content_type", ["text/plain", "image/gif", "image/svg+xml", ""])
def test_unsupported_types_are_refused_before_decoding(content_type):
    with pytest.raises(UnsupportedPhotoType):
        prepare_photo(image_bytes(), content_type)


@pytest.mark.parametrize(
    ("data", "content_type", "complaint"),
    [
        (b"not an image at all", "image/jpeg", "not a readable image"),
        (image_bytes()[:200], "image/jpeg", "not a readable image"),  # truncated
        (image_bytes("PNG"), "image/jpeg", "not a image/jpeg image"),  # claims to be what it isn't
    ],
    ids=["garbage", "truncated", "wrong-format"],
)
def test_files_that_are_not_what_they_claim_are_refused(data, content_type, complaint):
    with pytest.raises(InvalidPhoto, match=complaint):
        prepare_photo(data, content_type)


@pytest.mark.parametrize("side", [6000, 8000], ids=["over-limit", "over-twice-limit"])
def test_decompression_bombs_are_refused(side):
    """A one-bit PNG of side x side pixels is a few kilobytes on disk but would
    decode to tens of millions of pixels."""
    bomb = BytesIO()
    Image.new("1", (side, side)).save(bomb, "PNG")
    assert side * side > MAX_DECODED_PIXELS and len(bomb.getvalue()) < 100_000
    with pytest.raises(InvalidPhoto, match="too large"):
        prepare_photo(bomb.getvalue(), "image/png")


class MemoryPhotoStore:
    """An in-memory PhotoStore. The same contract as FileSystemPhotoStore."""

    def __init__(self) -> None:
        self._photos: dict[int, tuple[bytes, int]] = {}

    def save(self, animal_id: int, photo: bytes) -> None:
        previous = self._photos.get(animal_id, (b"", 0))[1]
        self._photos[animal_id] = (photo, previous + 1)

    def load(self, animal_id: int) -> bytes | None:
        return self._photos.get(animal_id, (None, None))[0]

    def version(self, animal_id: int) -> int | None:
        return self._photos.get(animal_id, (None, None))[1]


@pytest.fixture(params=["filesystem", "memory"])
def any_store(request, tmp_path):
    return FileSystemPhotoStore(tmp_path / "photos") if request.param == "filesystem" else MemoryPhotoStore()


def test_both_stores_keep_the_same_contract(any_store):
    """Liskov: whichever store the service is given, it behaves the same."""
    assert any_store.load(1) is None and any_store.version(1) is None

    any_store.save(1, b"first")
    first = any_store.version(1)
    any_store.save(1, b"second")

    assert any_store.load(1) == b"second"
    assert isinstance(any_store.version(1), int) and any_store.version(1) > first
    assert any_store.load(2) is None


def test_a_new_photo_always_gets_a_newer_version_even_within_one_clock_tick(tmp_path):
    store = FileSystemPhotoStore(tmp_path)
    store.save(3, b"first")
    future = store.version(3) + 10_000_000_000  # pretend the first save came later
    os.utime(tmp_path / "3.webp", ns=(future, future))

    store.save(3, b"second")

    assert store.version(3) > future


def test_the_filesystem_store_writes_whole_files_named_only_by_id(tmp_path):
    folder = tmp_path / "photos"
    store = FileSystemPhotoStore(folder)  # creates the folder itself
    for _ in range(5):
        store.save(7, b"photo")
    assert sorted(p.name for p in folder.iterdir()) == ["7.webp"]  # no temp files left behind
    for bad_id in (0, -1, True, "7", "../7"):
        with pytest.raises(ValueError):
            store.save(bad_id, b"x")


@pytest.fixture
def photos(service) -> PhotoService:
    return PhotoService(service, MemoryPhotoStore(), prepare=lambda data, content_type: b"webp:" + data)


def test_upload_stores_the_prepared_image_and_versions_its_url(service, photos):
    animal_id = _animal_in(service, S.AVAILABLE)
    assert photos.photo_url(animal_id) is None

    first = photos.upload(animal_id, b"raw", "image/jpeg")
    second = photos.upload(animal_id, b"raw2", "image/jpeg")

    assert photos.photo(animal_id) == b"webp:raw2"
    assert first.startswith(f"/api/animals/{animal_id}/photo?v=") and second != first


def test_photos_need_an_existing_animal_and_a_photo(service, photos):
    with pytest.raises(AnimalNotFound):
        photos.upload(999, b"raw", "image/jpeg")
    with pytest.raises(PhotoNotFound):
        photos.photo(_animal_in(service, S.AVAILABLE))


# --- offline adoptions ---------------------------------------------------------


def test_homes_found_adds_offline_adoptions_to_adopted_animals(service):
    assert service.homes_found() == 0
    service.record_offline_adoption({"animal_count": 300, "adopted_on": "2025-12-31", "note": "2018 to 2025"})
    service.record_offline_adoption({"animal_count": 2, "adopted_on": "2026-09-20"})
    _animal_in(service, S.ADOPTED)
    _animal_in(service, S.PENDING)  # not adopted yet: does not count

    assert service.homes_found() == 303
    assert [a.animal_count for a in service.offline_adoptions()] == [2, 300]  # newest first


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        ({"adopted_on": "2026-09-01"}, "missing field(s): animal_count"),
        ({"animal_count": 0, "adopted_on": "2026-09-01"}, "from 1 to 10000"),
        ({"animal_count": 10_001, "adopted_on": "2026-09-01"}, "from 1 to 10000"),
        ({"animal_count": True, "adopted_on": "2026-09-01"}, "from 1 to 10000"),
        ({"animal_count": "3", "adopted_on": "2026-09-01"}, "from 1 to 10000"),
        ({"animal_count": 3, "adopted_on": "2027-01-01"}, "future"),
        ({"animal_count": 3, "adopted_on": "2026-09-01", "note": "x" * 501}, "at most 500"),
        ({"animal_count": 3, "adopted_on": "2026-09-01", "by": "Salma"}, "unknown field(s): by"),
    ],
)
def test_invalid_offline_adoptions_are_rejected(service, payload, complaint):
    with pytest.raises(ValidationError, match=re.escape(complaint)):
        service.record_offline_adoption(payload)
    assert service.homes_found() == 0


# --- public profile details ----------------------------------------------------

PROFILE = {
    "born_on": "2026-08-01",
    "colour": "Rich golden",
    "personality": "Friendly",
    "weight_kg": "6.8",
    "about": "Loves everyone he meets.",
}


@pytest.mark.parametrize(
    ("born_on", "text"),
    [
        (None, None),
        (date(2026, 9, 20), "under a month"),
        (date(2026, 8, 29), "1 month"),
        (date(2026, 7, 30), "1 month"),  # two calendar months back, one full month lived
        (date(2026, 7, 29), "2 months"),
        (date(2025, 9, 30), "11 months"),
        (date(2025, 9, 29), "1 year"),
        (date(2022, 1, 1), "4 years"),
    ],
)
def test_age_is_counted_in_whole_months_and_years(born_on, text):
    assert age_text(born_on, TODAY) == text


@pytest.mark.parametrize(
    ("grams", "text"),
    [(None, None), (6_800, "6.8 kg"), (12_000, "12 kg"), (450, "0.45 kg"), (1, "0.001 kg"), (150_000, "150 kg")],
)
def test_weight_is_shown_in_kilograms_without_floats(grams, text):
    assert weight_text(grams) == text


def test_a_profile_is_saved_replaced_and_read_back(service):
    animal_id = _animal_in(service, S.AVAILABLE)
    assert service.profile(animal_id) == AnimalProfile()  # nothing written yet

    saved = service.update_profile(animal_id, PROFILE)
    assert saved.weight_grams == 6_800
    assert service.profile(animal_id) == saved

    # A new profile replaces the old one: fields left out are cleared.
    service.update_profile(animal_id, {"colour": "Golden"})
    assert service.profile(animal_id) == AnimalProfile(colour="Golden")


def test_blank_profile_fields_are_cleared(service):
    animal_id = _animal_in(service, S.AVAILABLE)
    service.update_profile(animal_id, PROFILE)
    service.update_profile(animal_id, {k: "" for k in PROFILE})
    assert service.profile(animal_id) == AnimalProfile()


@pytest.mark.parametrize(
    ("change", "complaint"),
    [
        ({"weight_kg": 6.8}, "as a string"),
        ({"weight_kg": "1e3"}, "as a string"),
        ({"weight_kg": "6,8"}, "as a string"),
        ({"weight_kg": "6.8901"}, "as a string"),
        ({"weight_kg": "\u0666"}, "as a string"),  # Arabic-Indic 6
        ({"weight_kg": "0"}, "more than 0"),
        ({"weight_kg": "150.001"}, "at most 150"),
        ({"born_on": "2027-01-01"}, "future"),
        ({"colour": "x" * 41}, "at most 40"),
        ({"personality": "x" * 61}, "at most 60"),
        ({"about": "x" * 1001}, "at most 1000"),
        ({"age": "2 months"}, "unknown field(s): age"),
    ],
)
def test_invalid_profiles_are_rejected(service, change, complaint):
    animal_id = _animal_in(service, S.AVAILABLE)
    with pytest.raises(ValidationError, match=re.escape(complaint)):
        service.update_profile(animal_id, {**PROFILE, **change})
    assert service.profile(animal_id) == AnimalProfile()


def test_profile_needs_an_existing_animal(service):
    with pytest.raises(AnimalNotFound):
        service.update_profile(999, PROFILE)
    with pytest.raises(AnimalNotFound):
        service.profile(999)


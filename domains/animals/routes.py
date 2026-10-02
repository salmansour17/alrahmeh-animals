"""HTTP endpoints for the animal domain.

Each handler does three things only: read the request, call one service method,
and turn the result into JSON. Validation, lifecycle rules and SQL all live
below this module. Domain exceptions are mapped to status codes once, by the
error handlers at the bottom, rather than with a try/except in every handler.

Two views of an animal: the public one leaves out staff notes and every medical
record except vaccinations; the staff one, behind @require_admin, has it all.
"""

from __future__ import annotations

from flask import Blueprint, Response, jsonify, request

from domains.animals.models import (
    Animal,
    MedicalRecord,
    PlacementRequest,
    StatusChange,
    ValidationError,
)
from domains.animals.photos import MAX_PHOTO_BYTES
from domains.animals.service import (
    AdoptionAlreadyApproved,
    AnimalNotFound,
    AnimalService,
    IllegalTransition,
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
from security import require_admin

# Every domain error, mapped once to a status code and a stable error name.
# Messages never contain applicant data, so they are safe to return.
ERROR_RESPONSES: dict[type[Exception], tuple[int, str]] = {
    ValidationError: (400, "validation_failed"),
    AnimalNotFound: (404, "not_found"),
    RequestNotFound: (404, "not_found"),
    PhotoNotFound: (404, "not_found"),
    UnsupportedPhotoType: (415, "unsupported_media_type"),
    IllegalTransition: (409, "illegal_transition"),
    TransitionConflict: (409, "transition_conflict"),
    RequestNotAccepted: (409, "request_not_accepted"),
    RequestAlreadyDecided: (409, "already_decided"),
    AdoptionAlreadyApproved: (409, "adoption_already_approved"),
    RequestConflict: (409, "request_conflict"),
}

# A versioned photo address never changes content, so browsers may keep it for
# a year; any other address is revalidated every time.
CACHE_VERSIONED = "public, max-age=31536000, immutable"
CACHE_UNVERSIONED = "no-cache"

# The public answer to a request form, identical whether the request was
# stored or a honeypot was caught: no id, so a bot cannot tell the difference.
RECEIVED = {"status": "received"}


def create_animals_blueprint(
    service: AnimalService, placements: PlacementService, photos: PhotoService
) -> Blueprint:
    """Build the blueprint around already-constructed services, so the
    choice of repository is made in create_app and nowhere in here."""
    bp = Blueprint("animals", __name__, url_prefix="/api/animals")

    def public(animal: Animal) -> dict:
        return {**_public(animal), "photo_url": photos.photo_url(animal.id)}

    @bp.get("/<int:animal_id>/photo")
    def get_photo(animal_id: int):
        response = Response(photos.photo(animal_id), mimetype="image/webp")
        # Never let a browser guess a different type for these bytes.
        response.headers["X-Content-Type-Options"] = "nosniff"
        current = str(photos.version(animal_id))
        response.headers["Cache-Control"] = (
            CACHE_VERSIONED if request.args.get("v") == current else CACHE_UNVERSIONED
        )
        return response

    @bp.put("/<int:animal_id>/photo")
    @require_admin
    def upload_photo(animal_id: int):
        # The 64 KiB limit set in create_app is raised for this route alone,
        # before the body is read.
        request.max_content_length = MAX_PHOTO_BYTES
        url = photos.upload(animal_id, request.get_data(), request.mimetype)
        return jsonify(photo_url=url)

    # --- public --------------------------------------------------------------

    @bp.get("")
    def list_animals():
        animals = service.list_animals(request.args.get("status"))
        return jsonify(animals=[public(animal) for animal in animals])

    @bp.get("/stats")
    def placement_stats():
        counts = service.placement_counts()
        return jsonify({status.value: count for status, count in counts.items()})

    @bp.get("/<int:animal_id>")
    def get_animal(animal_id: int):
        animal = service.get(animal_id)
        vaccinations = service.vaccinations(animal_id)
        return jsonify(
            **public(animal),
            vaccinations=[
                {"description": v.description, "occurred_on": v.occurred_on.isoformat()}
                for v in vaccinations
            ],
        )

    # Exception 3 of 3 to "every write gets @require_admin" (CLAUDE.md, Auth):
    # applicants are the public. It only creates an open request; the animal's
    # status changes only when staff decide.
    @bp.post("/<int:animal_id>/requests")
    def submit_request(animal_id: int):
        if not request.is_json:
            return jsonify(error="unsupported_media_type", detail="send application/json"), 415
        placements.submit(animal_id, request.get_json(silent=True))
        return jsonify(RECEIVED), 201

    # --- staff ---------------------------------------------------------------

    @bp.get("/<int:animal_id>/staff")
    @require_admin
    def get_animal_for_staff(animal_id: int):
        animal = service.get(animal_id)
        return jsonify(
            **public(animal),
            notes=animal.notes,
            medical_records=[_medical(r) for r in service.medical_history(animal_id)],
            status_history=[_change(c) for c in service.status_history(animal_id)],
        )

    @bp.post("")
    @require_admin
    def admit_animal():
        animal = service.admit(request.get_json(silent=True))
        return jsonify(**public(animal), notes=animal.notes), 201

    @bp.post("/<int:animal_id>/transitions")
    @require_admin
    def transition_animal(animal_id: int):
        animal = service.transition(animal_id, request.get_json(silent=True))
        return jsonify(public(animal))

    @bp.post("/<int:animal_id>/medical-records")
    @require_admin
    def add_medical_record(animal_id: int):
        record = service.record_medical(animal_id, request.get_json(silent=True))
        return jsonify(_medical(record)), 201

    _register_error_handlers(bp)
    return bp


def create_requests_blueprint(placements: PlacementService) -> Blueprint:
    """Staff-only: read adoption and foster requests and decide them."""
    bp = Blueprint("requests", __name__, url_prefix="/api/requests")

    @bp.get("")
    @require_admin
    def list_requests():
        requests = placements.list_requests(request.args.get("status"))
        return jsonify(requests=[_request(r) for r in requests])

    @bp.post("/<int:request_id>/decision")
    @require_admin
    def decide(request_id: int):
        return jsonify(_request(placements.decide(request_id, request.get_json(silent=True))))

    _register_error_handlers(bp)
    return bp


def _register_error_handlers(bp: Blueprint) -> None:
    for error_type, (status, name) in ERROR_RESPONSES.items():
        bp.register_error_handler(error_type, _error_response(status, name))


def _error_response(status: int, name: str):
    def handle(error: Exception):
        return jsonify(error=name, detail=str(error)), status

    return handle


def _request(placement: PlacementRequest) -> dict:
    """Staff view of a request, applicant details included. Only ever
    returned by @require_admin routes."""
    return {
        "id": placement.id,
        "animal_id": placement.animal_id,
        "kind": placement.kind.value,
        "applicant_name": placement.applicant_name,
        "applicant_email": placement.applicant_email,
        "message": placement.message,
        "outcome": placement.outcome.value,
        "submitted_at": placement.submitted_at,
    }


def _public(animal: Animal) -> dict:
    return {
        "id": animal.id,
        "name": animal.name,
        "species": animal.species,
        "breed": animal.breed,
        "intake_date": animal.intake_date.isoformat(),
        "status": animal.status.value,
    }


def _medical(record: MedicalRecord) -> dict:
    return {
        "id": record.id,
        "record_type": record.record_type.value,
        "description": record.description,
        "occurred_on": record.occurred_on.isoformat(),
    }


def _change(change: StatusChange) -> dict:
    return {
        "from": change.from_status.value,
        "to": change.to_status.value,
        "reason": change.reason,
        "changed_at": change.changed_at,
    }

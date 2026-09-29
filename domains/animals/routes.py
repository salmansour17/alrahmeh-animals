"""HTTP endpoints for the animal domain.

Each handler does three things only: read the request, call one service method,
and turn the result into JSON. Validation, lifecycle rules and SQL all live
below this module. Domain exceptions are mapped to status codes once, by the
error handlers at the bottom, rather than with a try/except in every handler.

Two views of an animal: the public one leaves out staff notes and every medical
record except vaccinations; the staff one, behind @require_admin, has it all.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from domains.animals.models import Animal, MedicalRecord, StatusChange, ValidationError
from domains.animals.service import (
    AnimalNotFound,
    AnimalService,
    IllegalTransition,
    TransitionConflict,
)
from security import require_admin


def create_animals_blueprint(service: AnimalService) -> Blueprint:
    """Build the blueprint around an already-constructed service, so the
    choice of repository is made in create_app and nowhere in here."""
    bp = Blueprint("animals", __name__, url_prefix="/api/animals")

    # --- public --------------------------------------------------------------

    @bp.get("")
    def list_animals():
        animals = service.list_animals(request.args.get("status"))
        return jsonify(animals=[_public(animal) for animal in animals])

    @bp.get("/<int:animal_id>")
    def get_animal(animal_id: int):
        animal = service.get(animal_id)
        vaccinations = service.vaccinations(animal_id)
        return jsonify(
            **_public(animal),
            vaccinations=[
                {"description": v.description, "occurred_on": v.occurred_on.isoformat()}
                for v in vaccinations
            ],
        )

    # --- staff ---------------------------------------------------------------

    @bp.get("/<int:animal_id>/staff")
    @require_admin
    def get_animal_for_staff(animal_id: int):
        animal = service.get(animal_id)
        return jsonify(
            **_public(animal),
            notes=animal.notes,
            medical_records=[_medical(r) for r in service.medical_history(animal_id)],
            status_history=[_change(c) for c in service.status_history(animal_id)],
        )

    @bp.post("")
    @require_admin
    def admit_animal():
        animal = service.admit(request.get_json(silent=True))
        return jsonify(**_public(animal), notes=animal.notes), 201

    @bp.post("/<int:animal_id>/transitions")
    @require_admin
    def transition_animal(animal_id: int):
        animal = service.transition(animal_id, request.get_json(silent=True))
        return jsonify(_public(animal))

    @bp.post("/<int:animal_id>/medical-records")
    @require_admin
    def add_medical_record(animal_id: int):
        record = service.record_medical(animal_id, request.get_json(silent=True))
        return jsonify(_medical(record)), 201

    # --- errors --------------------------------------------------------------

    @bp.errorhandler(ValidationError)
    def bad_request(error: ValidationError):
        return jsonify(error="validation_failed", detail=str(error)), 400

    @bp.errorhandler(AnimalNotFound)
    def not_found(error: AnimalNotFound):
        return jsonify(error="not_found", detail=str(error)), 404

    @bp.errorhandler(IllegalTransition)
    def illegal_transition(error: IllegalTransition):
        return jsonify(error="illegal_transition", detail=str(error)), 409

    @bp.errorhandler(TransitionConflict)
    def conflict(error: TransitionConflict):
        return jsonify(error="transition_conflict", detail=str(error)), 409

    return bp


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

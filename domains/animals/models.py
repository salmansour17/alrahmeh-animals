"""Entities, enums and input parsing for the animal intake and adoption domain.

Every status and record type is an Enum defined here, so no other module in the
project spells one as a bare string. The Enum values are the exact strings the
schema's CHECK constraints allow, which is what lets the repository store
`status.value` and read it back with `PlacementStatus(row["status"])`.

Input validation also lives here, in the `from_payload` constructors, so there
is exactly one place that decides what a valid request looks like. Routes pass
the raw JSON through untouched; they never check a field themselves.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from typing import Any, Mapping

NAME_MAX = 80
SPECIES_MAX = 40
BREED_MAX = 80
NOTES_MAX = 2000
DESCRIPTION_MAX = 500
REASON_MAX = 500


class PlacementStatus(StrEnum):
    """Where an animal is in the placement lifecycle. The legal moves between
    these are in service.ALLOWED_TRANSITIONS, not here."""

    AVAILABLE = "available"
    FOSTERING = "fostering"
    PENDING = "pending"
    ADOPTED = "adopted"


class MedicalRecordType(StrEnum):
    VACCINATION = "vaccination"
    TREATMENT = "treatment"
    CHECKUP = "checkup"


class ValidationError(ValueError):
    """A request body or query parameter that cannot become a domain object."""


@dataclass(frozen=True)
class Animal:
    id: int
    name: str
    species: str
    breed: str | None
    intake_date: date
    status: PlacementStatus
    notes: str | None


@dataclass(frozen=True)
class NewAnimal:
    """An animal being admitted: everything except what the database assigns."""

    name: str
    species: str
    breed: str | None
    intake_date: date
    notes: str | None

    @classmethod
    def from_payload(cls, payload: Any, today: date) -> NewAnimal:
        fields = _fields(
            payload,
            required={"name", "species", "intake_date"},
            optional={"breed", "notes"},
        )
        return cls(
            name=_text(fields, "name", NAME_MAX),
            species=_text(fields, "species", SPECIES_MAX),
            breed=_optional_text(fields, "breed", BREED_MAX),
            intake_date=_past_date(fields, "intake_date", today),
            notes=_optional_text(fields, "notes", NOTES_MAX),
        )


@dataclass(frozen=True)
class MedicalRecord:
    id: int
    animal_id: int
    record_type: MedicalRecordType
    description: str
    occurred_on: date


@dataclass(frozen=True)
class NewMedicalRecord:
    record_type: MedicalRecordType
    description: str
    occurred_on: date

    @classmethod
    def from_payload(cls, payload: Any, today: date) -> NewMedicalRecord:
        fields = _fields(
            payload,
            required={"record_type", "description", "occurred_on"},
            optional=set(),
        )
        return cls(
            record_type=_enum(fields, "record_type", MedicalRecordType),
            description=_text(fields, "description", DESCRIPTION_MAX),
            occurred_on=_past_date(fields, "occurred_on", today),
        )


@dataclass(frozen=True)
class TransitionRequest:
    """A request to move an animal to a new placement status."""

    to: PlacementStatus
    reason: str | None

    @classmethod
    def from_payload(cls, payload: Any) -> TransitionRequest:
        fields = _fields(payload, required={"to"}, optional={"reason"})
        return cls(
            to=_enum(fields, "to", PlacementStatus),
            reason=_optional_text(fields, "reason", REASON_MAX),
        )


@dataclass(frozen=True)
class StatusChange:
    """One row of an animal's placement history."""

    from_status: PlacementStatus
    to_status: PlacementStatus
    reason: str | None
    changed_at: str


def parse_status(raw: str | None) -> PlacementStatus | None:
    """Parse an optional ?status= filter. None means no filter."""
    if raw is None:
        return None
    return _enum({"status": raw}, "status", PlacementStatus)


# --- field helpers -----------------------------------------------------------
# Small and private: each checks one kind of field and raises ValidationError
# naming the field, so an error message always says what to fix.


def _fields(payload: Any, required: set[str], optional: set[str]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValidationError("request body must be a JSON object")
    unknown = sorted(set(payload) - required - optional)
    if unknown:
        raise ValidationError(f"unknown field(s): {', '.join(unknown)}")
    missing = sorted(required - set(payload))
    if missing:
        raise ValidationError(f"missing field(s): {', '.join(missing)}")
    return payload


def _text(fields: Mapping[str, Any], name: str, max_length: int) -> str:
    value = fields[name]
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"{name} must be at most {max_length} characters")
    return value


def _optional_text(fields: Mapping[str, Any], name: str, max_length: int) -> str | None:
    if fields.get(name) in (None, ""):
        return None
    return _text(fields, name, max_length)


def _past_date(fields: Mapping[str, Any], name: str, today: date) -> date:
    value = fields[name]
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be an ISO date string, e.g. 2026-09-29")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date, e.g. 2026-09-29") from None
    if parsed > today:
        raise ValidationError(f"{name} cannot be in the future")
    return parsed


def _enum(fields: Mapping[str, Any], name: str, enum_type: type[StrEnum]) -> Any:
    try:
        return enum_type(fields[name])
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValidationError(f"{name} must be one of: {allowed}") from None

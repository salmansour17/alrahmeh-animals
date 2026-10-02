"""SQLite persistence for the animal domain.

The only module in domains/animals that contains SQL. Every query uses `?`
placeholders, so a value supplied by a request is always passed to SQLite as
data and never spliced into the statement text.

Rows never leave this module as sqlite3.Row objects: each is mapped to a frozen
dataclass from models.py, so the service and routes have no idea a database is
involved.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from db.connection import Database
from domains.animals.models import (
    Animal,
    MedicalRecord,
    MedicalRecordType,
    NewAnimal,
    NewMedicalRecord,
    NewOfflineAdoption,
    NewPlacementRequest,
    OfflineAdoption,
    PlacementRequest,
    PlacementStatus,
    RequestKind,
    RequestOutcome,
    StatusChange,
    StatusMove,
)


class _Conflict(Exception):
    """Raised inside a transaction to roll it back; never leaves this module."""

class SqliteAnimalRepository:
    """Implements service.AnimalRepository against the shared SQLite file."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, animal: NewAnimal) -> Animal:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO animals (name, species, breed, date_of_intake, status, notes) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    animal.name,
                    animal.species,
                    animal.breed,
                    animal.intake_date.isoformat(),
                    PlacementStatus.AVAILABLE.value,
                    animal.notes,
                ),
            )
            new_id = cursor.lastrowid
        return Animal(
            id=new_id,
            name=animal.name,
            species=animal.species,
            breed=animal.breed,
            intake_date=animal.intake_date,
            status=PlacementStatus.AVAILABLE,
            notes=animal.notes,
        )

    def get(self, animal_id: int) -> Animal | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, name, species, breed, date_of_intake, status, notes FROM animals WHERE id = ?", (animal_id,)
            ).fetchone()
        return _to_animal(row) if row else None

    def list(self, status: PlacementStatus | None) -> list[Animal]:
        with self._database.unit_of_work() as connection:
            if status is None:
                rows = connection.execute(
                    "SELECT id, name, species, breed, date_of_intake, status, notes FROM animals ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, name, species, breed, date_of_intake, status, notes FROM animals WHERE status = ? ORDER BY id",
                    (status.value,),
                ).fetchall()
        return [_to_animal(row) for row in rows]

    def count_by_status(self) -> dict[PlacementStatus, int]:
        """How many animals are in each status. Statuses with no animals are
        simply absent here; the service fills them in."""
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS animals FROM animals GROUP BY status"
            ).fetchall()
        return {PlacementStatus(row["status"]): row["animals"] for row in rows}

    def add_offline_adoption(self, adoption: NewOfflineAdoption) -> OfflineAdoption:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO offline_adoptions (animal_count, adopted_on, note) VALUES (?, ?, ?)",
                (adoption.animal_count, adoption.adopted_on.isoformat(), adoption.note),
            )
            new_id = cursor.lastrowid
        return OfflineAdoption(new_id, adoption.animal_count, adoption.adopted_on, adoption.note)

    def offline_adoptions(self) -> list[OfflineAdoption]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT id, animal_count, adopted_on, note FROM offline_adoptions "
                "ORDER BY adopted_on DESC, id DESC"
            ).fetchall()
        return [
            OfflineAdoption(row["id"], row["animal_count"], date.fromisoformat(row["adopted_on"]), row["note"])
            for row in rows
        ]

    def offline_adoption_total(self) -> int:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT COALESCE(SUM(animal_count), 0) AS total FROM offline_adoptions"
            ).fetchone()
        return row["total"]

    def change_status(
        self,
        animal_id: int,
        expected: PlacementStatus,
        new: PlacementStatus,
        reason: str | None,
        close_open_requests: bool = False,
    ) -> bool:
        """Move an animal from `expected` to `new`, recording the change.

        Returns False, and writes nothing, if the animal was no longer in
        `expected` by the time the UPDATE ran. With close_open_requests, every
        open adoption or foster request for the animal is declined in the same
        transaction (used when an animal is adopted).
        """
        with self._database.unit_of_work() as connection:
            if not _move_animal(connection, StatusMove(animal_id, expected, new, reason)):
                return False
            if close_open_requests:
                connection.execute(
                    "UPDATE placement_requests SET outcome = ? WHERE animal_id = ? AND outcome = ?",
                    (RequestOutcome.DECLINED.value, animal_id, RequestOutcome.OPEN.value),
                )
        return True

    def status_history(self, animal_id: int) -> list[StatusChange]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT from_status, to_status, reason, changed_at FROM status_changes "
                "WHERE animal_id = ? ORDER BY id",
                (animal_id,),
            ).fetchall()
        return [
            StatusChange(
                from_status=PlacementStatus(row["from_status"]),
                to_status=PlacementStatus(row["to_status"]),
                reason=row["reason"],
                changed_at=row["changed_at"],
            )
            for row in rows
        ]

    def add_medical_record(self, animal_id: int, record: NewMedicalRecord) -> MedicalRecord:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO medical_records (animal_id, record_type, description, occurred_on) "
                "VALUES (?, ?, ?, ?)",
                (
                    animal_id,
                    record.record_type.value,
                    record.description,
                    record.occurred_on.isoformat(),
                ),
            )
            new_id = cursor.lastrowid
        return MedicalRecord(
            id=new_id,
            animal_id=animal_id,
            record_type=record.record_type,
            description=record.description,
            occurred_on=record.occurred_on,
        )

    def medical_records(
        self, animal_id: int, record_type: MedicalRecordType | None
    ) -> list[MedicalRecord]:
        with self._database.unit_of_work() as connection:
            if record_type is None:
                rows = connection.execute(
                    "SELECT id, animal_id, record_type, description, occurred_on FROM medical_records "
                    "WHERE animal_id = ? ORDER BY occurred_on, id",
                    (animal_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, animal_id, record_type, description, occurred_on FROM medical_records "
                    "WHERE animal_id = ? AND record_type = ? ORDER BY occurred_on, id",
                    (animal_id, record_type.value),
                ).fetchall()
        return [_to_medical_record(row) for row in rows]


class SqlitePlacementRepository:
    """Implements service.PlacementRepository: adoption and foster requests."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add_request(self, animal_id: int, request: NewPlacementRequest) -> PlacementRequest:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO placement_requests "
                "(animal_id, kind, applicant_name, applicant_email, message) VALUES (?, ?, ?, ?, ?)",
                (
                    animal_id,
                    request.kind.value,
                    request.applicant_name,
                    request.applicant_email,
                    request.message,
                ),
            )
            new_id = cursor.lastrowid
        return self.get_request(new_id)

    def get_request(self, request_id: int) -> PlacementRequest | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, animal_id, kind, applicant_name, applicant_email, message, outcome, "
                "submitted_at FROM placement_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
        return _to_request(row) if row else None

    def list_requests(self, outcome: RequestOutcome | None) -> list[PlacementRequest]:
        with self._database.unit_of_work() as connection:
            if outcome is None:
                rows = connection.execute(
                    "SELECT id, animal_id, kind, applicant_name, applicant_email, message, outcome, "
                    "submitted_at FROM placement_requests ORDER BY id"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, animal_id, kind, applicant_name, applicant_email, message, outcome, "
                    "submitted_at FROM placement_requests WHERE outcome = ? ORDER BY id",
                    (outcome.value,),
                ).fetchall()
        return [_to_request(row) for row in rows]

    def decide(
        self,
        request_id: int,
        expected: RequestOutcome,
        new: RequestOutcome,
        move: StatusMove | None,
        decline_open: frozenset[RequestKind],
    ) -> bool:
        """Record a decision and everything it causes, or none of it.

        In one transaction: the request moves from `expected` to `new` (only if
        it is still `expected`, so of two staff deciding at once exactly one
        wins); the animal moves if `move` says so (only if it is still in the
        expected status); and other open requests of the given kinds for the
        same animal are declined. If either guarded UPDATE finds the row
        already changed, the whole transaction rolls back and this returns
        False.
        """
        try:
            with self._database.unit_of_work() as connection:
                decided = connection.execute(
                    "UPDATE placement_requests SET outcome = ? WHERE id = ? AND outcome = ?",
                    (new.value, request_id, expected.value),
                )
                if decided.rowcount != 1:
                    raise _Conflict
                if move is not None and not _move_animal(connection, move):
                    raise _Conflict
                if move is not None:
                    for kind in decline_open:
                        connection.execute(
                            "UPDATE placement_requests SET outcome = ? "
                            "WHERE animal_id = ? AND kind = ? AND outcome = ? AND id != ?",
                            (
                                RequestOutcome.DECLINED.value,
                                move.animal_id,
                                kind.value,
                                RequestOutcome.OPEN.value,
                                request_id,
                            ),
                        )
        except _Conflict:
            return False
        return True


def _move_animal(connection: Any, move: StatusMove) -> bool:
    """The one place an animal's status changes, with its history row.

    The `AND status = ?` clause is what makes this safe when two members of
    staff act at once: SQLite serialises the two UPDATEs, the first matches the
    row, and the second finds the status already changed and matches nothing.
    """
    cursor = connection.execute(
        "UPDATE animals SET status = ? WHERE id = ? AND status = ?",
        (move.new.value, move.animal_id, move.expected.value),
    )
    if cursor.rowcount != 1:
        return False
    connection.execute(
        "INSERT INTO status_changes (animal_id, from_status, to_status, reason) VALUES (?, ?, ?, ?)",
        (move.animal_id, move.expected.value, move.new.value, move.reason),
    )
    return True


def _to_request(row: Any) -> PlacementRequest:
    return PlacementRequest(
        id=row["id"],
        animal_id=row["animal_id"],
        kind=RequestKind(row["kind"]),
        applicant_name=row["applicant_name"],
        applicant_email=row["applicant_email"],
        message=row["message"],
        outcome=RequestOutcome(row["outcome"]),
        submitted_at=row["submitted_at"],
    )


def _to_animal(row: Any) -> Animal:
    return Animal(
        id=row["id"],
        name=row["name"],
        species=row["species"],
        breed=row["breed"],
        intake_date=date.fromisoformat(row["date_of_intake"]),
        status=PlacementStatus(row["status"]),
        notes=row["notes"],
    )


def _to_medical_record(row: Any) -> MedicalRecord:
    return MedicalRecord(
        id=row["id"],
        animal_id=row["animal_id"],
        record_type=MedicalRecordType(row["record_type"]),
        description=row["description"],
        occurred_on=date.fromisoformat(row["occurred_on"]),
    )

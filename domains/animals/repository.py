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
    PlacementStatus,
    StatusChange,
)

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

    def change_status(
        self,
        animal_id: int,
        expected: PlacementStatus,
        new: PlacementStatus,
        reason: str | None,
    ) -> bool:
        """Move an animal from `expected` to `new`, recording the change.

        Returns False, and writes nothing, if the animal was no longer in
        `expected` by the time the UPDATE ran. The `AND status = ?` clause is
        what makes this safe when two members of staff act at once: SQLite
        serialises the two UPDATEs, the first one matches the row, and the
        second finds the status already changed and matches nothing.
        """
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "UPDATE animals SET status = ? WHERE id = ? AND status = ?",
                (new.value, animal_id, expected.value),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                "INSERT INTO status_changes (animal_id, from_status, to_status, reason) "
                "VALUES (?, ?, ?, ?)",
                (animal_id, expected.value, new.value, reason),
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

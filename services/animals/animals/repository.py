"""SQL Server persistence for the animal domain.

The only module in the animals package that contains SQL. Every query uses %s
placeholders, so a value supplied by a request is always sent to the database
as data and never spliced into the statement text.

Rows never leave this module as driver rows: each is mapped to a frozen
dataclass from models.py, so the service and routes have no idea a database is
involved.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from animals.models import (
    Animal,
    AnimalProfile,
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
from db import Database


class _Conflict(Exception):
    """Raised inside a transaction to roll it back; never leaves this module."""


class SqlAnimalRepository:
    """Implements service.AnimalRepository against this service's database."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, animal: NewAnimal) -> Animal:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO animals (name, species, breed, date_of_intake, status, notes) "
                "OUTPUT INSERTED.id VALUES (%s, %s, %s, %s, %s, %s)",
                (
                    animal.name,
                    animal.species,
                    animal.breed,
                    animal.intake_date.isoformat(),
                    PlacementStatus.AVAILABLE.value,
                    animal.notes,
                ),
            )
            new_id = cursor.fetchone()["id"]
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
                "SELECT id, name, species, breed, date_of_intake, status, notes FROM animals WHERE id = %s",
                (animal_id,),
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
                    "SELECT id, name, species, breed, date_of_intake, status, notes FROM animals "
                    "WHERE status = %s ORDER BY id",
                    (status.value,),
                ).fetchall()
        return [_to_animal(row) for row in rows]

    def count_by_status(self) -> dict[PlacementStatus, int]:
        """How many animals are in each status. Statuses with no animals are
        simply absent here; the service fills them in."""
        with self._database.unit_of_work() as connection:
            rows = connection.execute("SELECT status, COUNT(*) AS animals FROM animals GROUP BY status").fetchall()
        return {PlacementStatus(row["status"]): row["animals"] for row in rows}

    def profile(self, animal_id: int) -> AnimalProfile | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT born_on, colour, personality, weight_grams, about FROM animal_profiles WHERE animal_id = %s",
                (animal_id,),
            ).fetchone()
        if row is None:
            return None
        return AnimalProfile(
            born_on=_as_date(row["born_on"]) if row["born_on"] else None,
            colour=row["colour"],
            personality=row["personality"],
            weight_grams=row["weight_grams"],
            about=row["about"],
        )

    def save_profile(self, animal_id: int, profile: AnimalProfile) -> None:
        """Create or replace the animal's profile in one transaction.

        SQL Server has no INSERT ... ON CONFLICT, so this updates the row and
        inserts it only if there was none. UPDLOCK with SERIALIZABLE holds the
        key range from the UPDATE to the INSERT, so two saves at once cannot
        both find no row and both insert.
        """
        values = (
            profile.born_on.isoformat() if profile.born_on else None,
            profile.colour,
            profile.personality,
            profile.weight_grams,
            profile.about,
        )
        with self._database.unit_of_work() as connection:
            connection.execute(
                "UPDATE animal_profiles WITH (UPDLOCK, SERIALIZABLE) "
                "SET born_on = %s, colour = %s, personality = %s, weight_grams = %s, about = %s, "
                "updated_at = SYSUTCDATETIME() WHERE animal_id = %s; "
                "IF @@ROWCOUNT = 0 "
                "INSERT INTO animal_profiles (animal_id, born_on, colour, personality, weight_grams, about) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (*values, animal_id, animal_id, *values),
            )

    def add_offline_adoption(self, adoption: NewOfflineAdoption) -> OfflineAdoption:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO offline_adoptions (animal_count, adopted_on, note) OUTPUT INSERTED.id VALUES (%s, %s, %s)",
                (adoption.animal_count, adoption.adopted_on.isoformat(), adoption.note),
            )
            new_id = cursor.fetchone()["id"]
        return OfflineAdoption(new_id, adoption.animal_count, adoption.adopted_on, adoption.note)

    def offline_adoptions(self) -> list[OfflineAdoption]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT id, animal_count, adopted_on, note FROM offline_adoptions ORDER BY adopted_on DESC, id DESC"
            ).fetchall()
        return [
            OfflineAdoption(row["id"], row["animal_count"], _as_date(row["adopted_on"]), row["note"]) for row in rows
        ]

    def offline_adoption_total(self) -> int:
        with self._database.unit_of_work() as connection:
            row = connection.execute("SELECT COALESCE(SUM(animal_count), 0) AS total FROM offline_adoptions").fetchone()
        return row["total"]

    def change_status(
        self,
        animal_id: int,
        expected: PlacementStatus,
        new: PlacementStatus,
        reason: str | None,
        close_open_requests: bool = False,
        adoption_fell_through: bool = False,
    ) -> bool:
        """Move an animal from `expected` to `new`, recording the change.

        Returns False, and writes nothing, if the animal was no longer in
        `expected` by the time the UPDATE ran. With close_open_requests, every
        open adoption or foster request for the animal is declined in the same
        transaction (used when an animal is adopted). With
        adoption_fell_through, its approved adoption is declined in the same
        transaction (used when a pending animal goes back to available), while
        backup requests stay open.
        """
        with self._database.unit_of_work() as connection:
            if not _move_animal(connection, StatusMove(animal_id, expected, new, reason)):
                return False
            if close_open_requests:
                connection.execute(
                    "UPDATE placement_requests SET outcome = %s WHERE animal_id = %s AND outcome = %s",
                    (RequestOutcome.DECLINED.value, animal_id, RequestOutcome.OPEN.value),
                )
            if adoption_fell_through:
                connection.execute(
                    "UPDATE placement_requests SET outcome = %s WHERE animal_id = %s AND kind = %s AND outcome = %s",
                    (
                        RequestOutcome.DECLINED.value,
                        animal_id,
                        RequestKind.ADOPTION.value,
                        RequestOutcome.APPROVED.value,
                    ),
                )
        return True

    def status_history(self, animal_id: int) -> list[StatusChange]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT from_status, to_status, reason, changed_at FROM status_changes "
                "WHERE animal_id = %s ORDER BY id",
                (animal_id,),
            ).fetchall()
        return [
            StatusChange(
                from_status=PlacementStatus(row["from_status"]),
                to_status=PlacementStatus(row["to_status"]),
                reason=row["reason"],
                changed_at=_timestamp(row["changed_at"]),
            )
            for row in rows
        ]

    def add_medical_record(self, animal_id: int, record: NewMedicalRecord) -> MedicalRecord:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO medical_records (animal_id, record_type, description, occurred_on) "
                "OUTPUT INSERTED.id VALUES (%s, %s, %s, %s)",
                (
                    animal_id,
                    record.record_type.value,
                    record.description,
                    record.occurred_on.isoformat(),
                ),
            )
            new_id = cursor.fetchone()["id"]
        return MedicalRecord(
            id=new_id,
            animal_id=animal_id,
            record_type=record.record_type,
            description=record.description,
            occurred_on=record.occurred_on,
        )

    def medical_records(self, animal_id: int, record_type: MedicalRecordType | None) -> list[MedicalRecord]:
        with self._database.unit_of_work() as connection:
            if record_type is None:
                rows = connection.execute(
                    "SELECT id, animal_id, record_type, description, occurred_on FROM medical_records "
                    "WHERE animal_id = %s ORDER BY occurred_on, id",
                    (animal_id,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, animal_id, record_type, description, occurred_on FROM medical_records "
                    "WHERE animal_id = %s AND record_type = %s ORDER BY occurred_on, id",
                    (animal_id, record_type.value),
                ).fetchall()
        return [_to_medical_record(row) for row in rows]


class SqlPlacementRepository:
    """Implements service.PlacementRepository: adoption and foster requests."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add_request(self, animal_id: int, request: NewPlacementRequest) -> PlacementRequest:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO placement_requests "
                "(animal_id, kind, applicant_name, applicant_email, message) "
                "OUTPUT INSERTED.id VALUES (%s, %s, %s, %s, %s)",
                (
                    animal_id,
                    request.kind.value,
                    request.applicant_name,
                    request.applicant_email,
                    request.message,
                ),
            )
            new_id = cursor.fetchone()["id"]
        return self.get_request(new_id)

    def get_request(self, request_id: int) -> PlacementRequest | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, animal_id, kind, applicant_name, applicant_email, message, outcome, "
                "submitted_at FROM placement_requests WHERE id = %s",
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
                    "submitted_at FROM placement_requests WHERE outcome = %s ORDER BY id",
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
                    "UPDATE placement_requests SET outcome = %s WHERE id = %s AND outcome = %s",
                    (new.value, request_id, expected.value),
                )
                if decided.rowcount != 1:
                    raise _Conflict
                if move is not None and not _move_animal(connection, move):
                    raise _Conflict
                if move is not None:
                    for kind in decline_open:
                        connection.execute(
                            "UPDATE placement_requests SET outcome = %s "
                            "WHERE animal_id = %s AND kind = %s AND outcome = %s AND id != %s",
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


class SqlPhotoStore:
    """Implements service.PhotoStore: one row per animal in animal_photos.

    Photos live in the database rather than on disk because a Container App's
    disk is wiped when it scales to zero (ADR-7). The bytes stored are always
    the re-encoded WebP from photos.prepare_photo, never the upload itself.
    """

    def __init__(self, database: Database) -> None:
        self._database = database

    def save(self, animal_id: int, photo: bytes) -> None:
        """Replace an animal's photo, moving its version on by one.

        UPDLOCK with SERIALIZABLE holds the key from the UPDATE to the INSERT,
        so two uploads at once cannot both find no row and both insert. Either
        upload may win; neither leaves half a photo, because it is one row
        written in one transaction.
        """
        # pymssql sends `bytes` as text, which SQL Server will not put in a
        # VARBINARY column; a bytearray is sent as binary.
        binary = bytearray(photo)
        with self._database.unit_of_work() as connection:
            connection.execute(
                "UPDATE animal_photos WITH (UPDLOCK, SERIALIZABLE) "
                "SET photo = %s, version = version + 1, updated_at = SYSUTCDATETIME() "
                "WHERE animal_id = %s; "
                "IF @@ROWCOUNT = 0 "
                "INSERT INTO animal_photos (animal_id, photo) VALUES (%s, %s)",
                (binary, animal_id, animal_id, binary),
            )

    def load(self, animal_id: int) -> bytes | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute("SELECT photo FROM animal_photos WHERE animal_id = %s", (animal_id,)).fetchone()
        return bytes(row["photo"]) if row else None

    def version(self, animal_id: int) -> int | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute("SELECT version FROM animal_photos WHERE animal_id = %s", (animal_id,)).fetchone()
        return row["version"] if row else None

    def versions(self, animal_ids: list[int]) -> dict[int, int]:
        """Reads every photo's version (never the photo bytes) in one query
        and keeps the ones asked for. That avoids building an IN list, which
        SQL Server caps at about 2,100 parameters."""
        if not animal_ids:
            return {}
        with self._database.unit_of_work() as connection:
            rows = connection.execute("SELECT animal_id, version FROM animal_photos").fetchall()
        wanted = set(animal_ids)
        return {row["animal_id"]: row["version"] for row in rows if row["animal_id"] in wanted}


def _move_animal(connection: Any, move: StatusMove) -> bool:
    """The one place an animal's status changes, with its history row.

    The `AND status = %s` clause is what makes this safe when two members of
    staff act at once: the database locks the row for the first UPDATE, and the
    second, once it gets the row, finds the status already changed and matches
    nothing.
    """
    cursor = connection.execute(
        "UPDATE animals SET status = %s WHERE id = %s AND status = %s",
        (move.new.value, move.animal_id, move.expected.value),
    )
    if cursor.rowcount != 1:
        return False
    connection.execute(
        "INSERT INTO status_changes (animal_id, from_status, to_status, reason) VALUES (%s, %s, %s, %s)",
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
        submitted_at=_timestamp(row["submitted_at"]),
    )


def _to_animal(row: Any) -> Animal:
    return Animal(
        id=row["id"],
        name=row["name"],
        species=row["species"],
        breed=row["breed"],
        intake_date=_as_date(row["date_of_intake"]),
        status=PlacementStatus(row["status"]),
        notes=row["notes"],
    )


def _to_medical_record(row: Any) -> MedicalRecord:
    return MedicalRecord(
        id=row["id"],
        animal_id=row["animal_id"],
        record_type=MedicalRecordType(row["record_type"]),
        description=row["description"],
        occurred_on=_as_date(row["occurred_on"]),
    )


def _as_date(value: Any) -> date:
    """DATE columns arrive from pymssql as datetime.date already. This only
    narrows the type for the dataclass and fails loudly if that ever changes."""
    if not isinstance(value, date):
        raise TypeError(f"expected a DATE column, got {type(value).__name__}")
    return value


def _timestamp(value: datetime) -> str:
    """DATETIME2 columns arrive as datetime. The API has always shown them as
    "YYYY-MM-DD HH:MM:SS" in UTC, so they are formatted back to that."""
    return value.strftime("%Y-%m-%d %H:%M:%S")

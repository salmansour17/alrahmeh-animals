"""SQL Server persistence for the donation ledger.

The only module in the donations package that contains SQL, all of it with %s
placeholders. There is deliberately no update or delete method: the ledger is
append-only, and the class's shape says so. The trigger in 001_init.sql backs
that up for anything that bypasses this class.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from db import Database, IntegrityError
from donations.models import (
    Donation,
    DonationPurpose,
    ImpactSummary,
    NewDonation,
    PageRequest,
    ProviderCharge,
)


class _AlreadyRecorded(Exception):
    """Raised inside a transaction to roll it back; never leaves this module."""


class SqlDonationRepository:
    """Implements service.DonationRepository against this service's database."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, donation: NewDonation) -> Donation:
        with self._database.unit_of_work() as connection:
            new_id = _insert_donation(connection, donation)
        return Donation(
            id=new_id,
            donor_name=donation.donor_name,
            amount_fils=donation.amount_fils,
            purpose=donation.purpose,
            earmarked_animal_id=donation.earmarked_animal_id,
            received_on=donation.received_on,
        )

    def add_paid(self, donation: NewDonation, charge: ProviderCharge) -> Donation | None:
        """Record a card donation and the provider charge behind it together,
        or neither.

        Returns None if this session was already recorded. The check is the
        database's UNIQUE constraint, not a SELECT beforehand: a SELECT-then-
        INSERT would let two deliveries of the same webhook both see "not
        recorded yet" and both insert.
        """
        try:
            with self._database.unit_of_work() as connection:
                donation_id = _insert_donation(connection, donation)
                try:
                    connection.execute(
                        "INSERT INTO stripe_payments "
                        "(session_id, donation_id, charged_amount_minor, charged_currency) "
                        "VALUES (%s, %s, %s, %s)",
                        (charge.session_id, donation_id, charge.amount_minor, charge.currency),
                    )
                except IntegrityError as error:
                    # 2627/2601: the UNIQUE session_id is already there. Undo
                    # the donation insert above: unit_of_work rolls back.
                    if error.args and error.args[0] in (2627, 2601):
                        raise _AlreadyRecorded from error
                    raise
        except _AlreadyRecorded:
            return None
        return self.get(donation_id)

    def get(self, donation_id: int) -> Donation | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, donor_name, amount_fils, purpose, earmarked_animal_id, received_at "
                "FROM donations WHERE id = %s",
                (donation_id,),
            ).fetchone()
        return _to_donation(row) if row else None

    def list(self, page: PageRequest) -> list[Donation]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT id, donor_name, amount_fils, purpose, earmarked_animal_id, received_at "
                "FROM donations ORDER BY received_at DESC, id DESC "
                "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
                (page.offset, page.limit),
            ).fetchall()
        return [_to_donation(row) for row in rows]

    def impact(self) -> ImpactSummary:
        """All homepage figures, computed by the database from the ledger as it
        is now.

        The two SELECTs run in one SERIALIZABLE transaction so they read the
        same rows. Without it, a donation committed between them would make
        the headline total disagree with the per-purpose totals.
        """
        with self._database.unit_of_work() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            headline = connection.execute(
                "SELECT COALESCE(SUM(amount_fils), 0) AS total_fils, "
                "COUNT(*) AS donation_count, "
                "COUNT(DISTINCT earmarked_animal_id) AS animals_helped "
                "FROM donations"
            ).fetchone()
            by_purpose = connection.execute(
                "SELECT purpose, COALESCE(SUM(amount_fils), 0) AS total_fils "
                "FROM donations GROUP BY purpose"
            ).fetchall()
        found = {DonationPurpose(row["purpose"]): row["total_fils"] for row in by_purpose}
        return ImpactSummary(
            total_raised_fils=headline["total_fils"],
            donation_count=headline["donation_count"],
            # Iterating the enum, not the rows, is what makes a purpose with no
            # donations yet appear as 0 instead of being missing.
            totals_by_purpose_fils={purpose: found.get(purpose, 0) for purpose in DonationPurpose},
            animals_helped=headline["animals_helped"],
        )


def _insert_donation(connection: Any, donation: NewDonation) -> int:
    """The one INSERT into the ledger, shared by staff-recorded and card
    donations so the two can never write rows differently."""
    cursor = connection.execute(
        "INSERT INTO donations "
        "(donor_name, amount_fils, purpose, earmarked_animal_id, received_at) "
        "OUTPUT INSERTED.id VALUES (%s, %s, %s, %s, %s)",
        (
            donation.donor_name,
            donation.amount_fils,
            donation.purpose.value,
            donation.earmarked_animal_id,
            donation.received_on.isoformat(),
        ),
    )
    return cursor.fetchone()["id"]


def _to_donation(row: Any) -> Donation:
    return Donation(
        id=row["id"],
        donor_name=row["donor_name"],
        amount_fils=row["amount_fils"],
        purpose=DonationPurpose(row["purpose"]),
        earmarked_animal_id=row["earmarked_animal_id"],
        received_on=_as_date(row["received_at"]),
    )


def _as_date(value: Any) -> date:
    """DATE columns arrive from pymssql as datetime.date already. This only
    narrows the type for the dataclass and fails loudly if that ever changes."""
    if not isinstance(value, date):
        raise TypeError(f"expected a DATE column, got {type(value).__name__}")
    return value

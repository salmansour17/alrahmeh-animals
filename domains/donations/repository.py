"""SQLite persistence for the donation ledger.

The only module in domains/donations that contains SQL, all of it with `?`
placeholders. There is deliberately no update or delete method: the ledger is
append-only, and the class's shape says so. The schema's triggers back that up
for anything that bypasses this class.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from db.connection import Database
from domains.donations.models import (
    Donation,
    DonationPurpose,
    ImpactSummary,
    NewDonation,
    PageRequest,
)


class SqliteDonationRepository:
    """Implements service.DonationRepository against the shared SQLite file."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, donation: NewDonation) -> Donation:
        with self._database.unit_of_work() as connection:
            cursor = connection.execute(
                "INSERT INTO donations "
                "(donor_name, amount_fils, purpose, earmarked_animal_id, received_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    donation.donor_name,
                    donation.amount_fils,
                    donation.purpose.value,
                    donation.earmarked_animal_id,
                    donation.received_on.isoformat(),
                ),
            )
            new_id = cursor.lastrowid
        return Donation(
            id=new_id,
            donor_name=donation.donor_name,
            amount_fils=donation.amount_fils,
            purpose=donation.purpose,
            earmarked_animal_id=donation.earmarked_animal_id,
            received_on=donation.received_on,
        )

    def get(self, donation_id: int) -> Donation | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, donor_name, amount_fils, purpose, earmarked_animal_id, received_at "
                "FROM donations WHERE id = ?",
                (donation_id,),
            ).fetchone()
        return _to_donation(row) if row else None

    def list(self, page: PageRequest) -> list[Donation]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                "SELECT id, donor_name, amount_fils, purpose, earmarked_animal_id, received_at "
                "FROM donations ORDER BY received_at DESC, id DESC LIMIT ? OFFSET ?",
                (page.limit, page.offset),
            ).fetchall()
        return [_to_donation(row) for row in rows]

    def impact(self) -> ImpactSummary:
        """All homepage figures, computed by SQLite from the ledger as it is now.

        The two SELECTs run inside one explicit transaction so they read the
        same snapshot. Without it, a donation committed between them would make
        the headline total disagree with the per-purpose totals.
        """
        with self._database.unit_of_work() as connection:
            connection.execute("BEGIN")
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


def _to_donation(row: Any) -> Donation:
    return Donation(
        id=row["id"],
        donor_name=row["donor_name"],
        amount_fils=row["amount_fils"],
        purpose=DonationPurpose(row["purpose"]),
        earmarked_animal_id=row["earmarked_animal_id"],
        # [:10] keeps the date part even if a row ever took the schema's
        # datetime('now') default instead of the date the service supplies.
        received_on=date.fromisoformat(row["received_at"][:10]),
    )

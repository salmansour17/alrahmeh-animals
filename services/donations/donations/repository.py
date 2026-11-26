"""SQL Server persistence for the donation ledger.

The only module in the donations package that contains SQL, all of it with %s
placeholders. There is deliberately no update or delete method: the ledger is
append-only, and the class's shape says so. The trigger in 001_init.sql backs
that up for anything that bypasses this class. A correction is a new row, a
reversal (003_ledger_reversals.sql), written by reverse().
"""

from __future__ import annotations

from datetime import date
from typing import Any

from db import Database, IntegrityError
from donations.models import (
    Donation,
    DonationKind,
    DonationPurpose,
    ImpactSummary,
    LedgerSum,
    NewDonation,
    PageRequest,
    ProviderCharge,
    ReversalOutcome,
    net_impact,
)

# SQL Server error numbers, checked against a real server (2026-11-26):
# 2627 a UNIQUE constraint, 2601 a unique index. The ledger's "reversed only
# once" rule is the filtered unique index ux_donations_reversed_once.
_DUPLICATE_KEY = (2627, 2601)

# Every read of a ledger row goes through this, so every row comes back with
# the id of the reversal that cancels it (if any), found by a self-join: the
# gift itself is never edited to say so.
_SELECT_DONATIONS = (
    "SELECT d.id, d.donor_name, d.amount_fils, d.purpose, d.earmarked_animal_id, d.received_at, "
    "d.kind, d.reverses_donation_id, d.reversal_reason, r.id AS reversed_by_id "
    "FROM donations AS d LEFT JOIN donations AS r ON r.reverses_donation_id = d.id"
)


class _AlreadyRecorded(Exception):
    """Raised inside a transaction to roll it back; never leaves this module."""


class _AlreadyReversed(Exception):
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
                    if _is_duplicate(error):
                        raise _AlreadyRecorded from error
                    raise
        except _AlreadyRecorded:
            return None
        return self.get(donation_id)

    def get(self, donation_id: int) -> Donation | None:
        with self._database.unit_of_work() as connection:
            return _get(connection, donation_id)

    def list(self, page: PageRequest) -> list[Donation]:
        with self._database.unit_of_work() as connection:
            rows = connection.execute(
                _SELECT_DONATIONS + " ORDER BY d.received_at DESC, d.id DESC OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
                (page.offset, page.limit),
            ).fetchall()
        return [_to_donation(row) for row in rows]

    def reverse(self, donation_id: int, reason: str, recorded_on: date) -> tuple[ReversalOutcome, Donation | None]:
        """Add a reversal that cancels gift donation_id, in one transaction.

        The new row is built by the database from the gift itself (INSERT ...
        SELECT): amount, currency, purpose and earmark are copied, never taken
        from a request. The donor's name is not copied: the reversal links to
        the gift, which already holds it.

        The filtered unique index decides "reversed only once", not a SELECT
        beforehand: two staff clicking at the same moment both get past any
        SELECT, but only one INSERT can win; the other gets ALREADY_REVERSED.
        """
        try:
            with self._database.unit_of_work() as connection:
                try:
                    row = connection.execute(
                        "INSERT INTO donations "
                        "(donor_name, amount_fils, currency, purpose, earmarked_animal_id, received_at, "
                        "kind, reverses_donation_id, reversal_reason) "
                        "OUTPUT INSERTED.id "
                        "SELECT NULL, amount_fils, currency, purpose, earmarked_animal_id, %s, %s, id, %s "
                        "FROM donations WHERE id = %s AND kind = %s",
                        (
                            recorded_on.isoformat(),
                            DonationKind.REVERSAL.value,
                            reason,
                            donation_id,
                            DonationKind.GIFT.value,
                        ),
                    ).fetchone()
                except IntegrityError as error:
                    if _is_duplicate(error):
                        raise _AlreadyReversed from error
                    raise
                if row is None:
                    # Nothing was inserted: the id is unknown, or not a gift.
                    target = _get(connection, donation_id)
                    outcome = ReversalOutcome.NOT_FOUND if target is None else ReversalOutcome.NOT_A_GIFT
                    return outcome, None
                return ReversalOutcome.REVERSED, _get(connection, row["id"])
        except _AlreadyReversed:
            return ReversalOutcome.ALREADY_REVERSED, None

    def impact(self) -> ImpactSummary:
        """All homepage figures, computed from the ledger as it is now: gifts
        minus reversals (models.net_impact applies the sign).

        The two SELECTs run in one SERIALIZABLE transaction so they read the
        same rows. Without it, a donation or a reversal committed between them
        would make the totals disagree with the count of animals helped.
        """
        with self._database.unit_of_work() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            sums = connection.execute(
                "SELECT purpose, kind, SUM(amount_fils) AS total_fils, COUNT(*) AS row_count "
                "FROM donations GROUP BY purpose, kind"
            ).fetchall()
            # An animal is helped by a gift that still stands: its reversal,
            # if any, takes it out of the count.
            helped = connection.execute(
                "SELECT COUNT(DISTINCT g.earmarked_animal_id) AS animals_helped FROM donations AS g "
                "WHERE g.kind = %s AND NOT EXISTS "
                "(SELECT 1 FROM donations AS r WHERE r.reverses_donation_id = g.id)",
                (DonationKind.GIFT.value,),
            ).fetchone()
        return net_impact(
            (
                LedgerSum(
                    DonationPurpose(row["purpose"]), DonationKind(row["kind"]), row["total_fils"], row["row_count"]
                )
                for row in sums
            ),
            helped["animals_helped"],
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


def _get(connection: Any, donation_id: int) -> Donation | None:
    row = connection.execute(_SELECT_DONATIONS + " WHERE d.id = %s", (donation_id,)).fetchone()
    return _to_donation(row) if row else None


def _is_duplicate(error: IntegrityError) -> bool:
    return bool(error.args) and error.args[0] in _DUPLICATE_KEY


def _to_donation(row: Any) -> Donation:
    return Donation(
        id=row["id"],
        donor_name=row["donor_name"],
        amount_fils=row["amount_fils"],
        purpose=DonationPurpose(row["purpose"]),
        earmarked_animal_id=row["earmarked_animal_id"],
        received_on=_as_date(row["received_at"]),
        kind=DonationKind(row["kind"]),
        reverses_donation_id=row["reverses_donation_id"],
        reversal_reason=row["reversal_reason"],
        reversed_by_id=row["reversed_by_id"],
    )


def _as_date(value: Any) -> date:
    """DATE columns arrive from pymssql as datetime.date already. This only
    narrows the type for the dataclass and fails loudly if that ever changes."""
    if not isinstance(value, date):
        raise TypeError(f"expected a DATE column, got {type(value).__name__}")
    return value

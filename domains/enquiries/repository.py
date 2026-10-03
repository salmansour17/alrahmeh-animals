"""SQLite persistence for enquiries: the only module here that contains SQL."""

from __future__ import annotations

from typing import Any

from db.connection import Database
from domains.enquiries.models import Enquiry, EnquiryFilter, NewEnquiry, Topic


class SqliteEnquiryRepository:
    """Implements service.EnquiryRepository against the shared SQLite file."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, enquiry: NewEnquiry) -> None:
        with self._database.unit_of_work() as connection:
            connection.execute(
                "INSERT INTO enquiries (topic, name, email, subject, message) VALUES (?, ?, ?, ?, ?)",
                (enquiry.topic.value, enquiry.name, enquiry.email, enquiry.subject, enquiry.message),
            )

    def get(self, enquiry_id: int) -> Enquiry | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, topic, name, email, subject, message, handled, received_at "
                "FROM enquiries WHERE id = ?",
                (enquiry_id,),
            ).fetchone()
        return _to_enquiry(row) if row else None

    def list(self, which: EnquiryFilter) -> list[Enquiry]:
        with self._database.unit_of_work() as connection:
            if which.handled is None:
                rows = connection.execute(
                    "SELECT id, topic, name, email, subject, message, handled, received_at "
                    "FROM enquiries ORDER BY id DESC LIMIT ? OFFSET ?",
                    (which.limit, which.offset),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, topic, name, email, subject, message, handled, received_at "
                    "FROM enquiries WHERE handled = ? ORDER BY id DESC LIMIT ? OFFSET ?",
                    (int(which.handled), which.limit, which.offset),
                ).fetchall()
        return [_to_enquiry(row) for row in rows]

    def mark_handled(self, enquiry_id: int) -> None:
        """Idempotent: marking an already handled message again changes nothing."""
        with self._database.unit_of_work() as connection:
            connection.execute("UPDATE enquiries SET handled = 1 WHERE id = ?", (enquiry_id,))


def _to_enquiry(row: Any) -> Enquiry:
    return Enquiry(
        id=row["id"],
        topic=Topic(row["topic"]),
        name=row["name"],
        email=row["email"],
        subject=row["subject"],
        message=row["message"],
        handled=bool(row["handled"]),
        received_at=row["received_at"],
    )

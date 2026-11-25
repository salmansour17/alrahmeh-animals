"""SQL Server persistence for enquiries: the only module here that contains SQL."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from db import Database
from enquiries.models import Enquiry, EnquiryFilter, NewEnquiry, Topic


class SqlEnquiryRepository:
    """Implements service.EnquiryRepository against this service's database."""

    def __init__(self, database: Database) -> None:
        self._database = database

    def add(self, enquiry: NewEnquiry) -> None:
        with self._database.unit_of_work() as connection:
            connection.execute(
                "INSERT INTO enquiries (topic, name, email, subject, message) VALUES (%s, %s, %s, %s, %s)",
                (enquiry.topic.value, enquiry.name, enquiry.email, enquiry.subject, enquiry.message),
            )

    def get(self, enquiry_id: int) -> Enquiry | None:
        with self._database.unit_of_work() as connection:
            row = connection.execute(
                "SELECT id, topic, name, email, subject, message, handled, received_at FROM enquiries WHERE id = %s",
                (enquiry_id,),
            ).fetchone()
        return _to_enquiry(row) if row else None

    def list(self, which: EnquiryFilter) -> list[Enquiry]:
        with self._database.unit_of_work() as connection:
            if which.handled is None:
                rows = connection.execute(
                    "SELECT id, topic, name, email, subject, message, handled, received_at "
                    "FROM enquiries ORDER BY id DESC OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
                    (which.offset, which.limit),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT id, topic, name, email, subject, message, handled, received_at "
                    "FROM enquiries WHERE handled = %s ORDER BY id DESC "
                    "OFFSET %s ROWS FETCH NEXT %s ROWS ONLY",
                    (which.handled, which.offset, which.limit),
                ).fetchall()
        return [_to_enquiry(row) for row in rows]

    def mark_handled(self, enquiry_id: int) -> None:
        """Idempotent: marking an already handled message again changes nothing."""
        with self._database.unit_of_work() as connection:
            connection.execute("UPDATE enquiries SET handled = 1 WHERE id = %s", (enquiry_id,))


def _to_enquiry(row: Any) -> Enquiry:
    return Enquiry(
        id=row["id"],
        topic=Topic(row["topic"]),
        name=row["name"],
        email=row["email"],
        subject=row["subject"],
        message=row["message"],
        handled=bool(row["handled"]),
        received_at=_timestamp(row["received_at"]),
    )


def _timestamp(value: datetime) -> str:
    """DATETIME2 columns arrive as datetime. The API has always shown them as
    "YYYY-MM-DD HH:MM:SS" in UTC, so they are formatted back to that."""
    return value.strftime("%Y-%m-%d %H:%M:%S")

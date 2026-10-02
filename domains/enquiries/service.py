"""Business rules for enquiries. Small on purpose: the public sends, staff read
and mark handled. The service owns the repository interface it depends on."""

from __future__ import annotations

from typing import Any, Protocol

from domains.enquiries.models import Enquiry, EnquiryFilter, NewEnquiry, is_honeypot


class EnquiryNotFound(LookupError):
    def __init__(self, enquiry_id: int) -> None:
        super().__init__(f"no message with id {enquiry_id}")


class EnquiryRepository(Protocol):
    def add(self, enquiry: NewEnquiry) -> None: ...

    def get(self, enquiry_id: int) -> Enquiry | None: ...

    def list(self, which: EnquiryFilter) -> list[Enquiry]: ...

    def mark_handled(self, enquiry_id: int) -> None: ...


class EnquiryService:
    def __init__(self, repository: EnquiryRepository) -> None:
        self._repository = repository

    def receive(self, payload: Any) -> None:
        """Store a message from the public. A honeypot hit is accepted silently
        and stored nowhere; the caller answers both the same way."""
        if is_honeypot(payload):
            return
        self._repository.add(NewEnquiry.from_payload(payload))

    def list_enquiries(
        self, handled: str | None = None, limit: str | None = None, offset: str | None = None
    ) -> list[Enquiry]:
        return self._repository.list(EnquiryFilter.from_query(handled, limit, offset))

    def mark_handled(self, enquiry_id: int) -> Enquiry:
        if self._repository.get(enquiry_id) is None:
            raise EnquiryNotFound(enquiry_id)
        self._repository.mark_handled(enquiry_id)
        return self._repository.get(enquiry_id)

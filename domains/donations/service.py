"""Business rules for the donation ledger.

The service owns two small interfaces and depends on nothing else: the
DonationRepository it stores through, and the AnimalDirectory it asks whether
an earmarked animal exists. Neither mentions SQLite or the animal package;
create_app supplies the concrete objects.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Protocol

from domains.donations.models import (
    Donation,
    ImpactSummary,
    NewDonation,
    PageRequest,
    ValidationError,
)


class DonationNotFound(LookupError):
    def __init__(self, donation_id: int) -> None:
        super().__init__(f"no donation with id {donation_id}")


class UnknownEarmarkedAnimal(ValidationError):
    """The earmarked animal id does not match any animal. A ValidationError,
    because it is the request that is wrong, so it answers 400 like one."""

    def __init__(self, animal_id: int) -> None:
        super().__init__(f"earmarked_animal_id {animal_id} does not match any animal")


class AnimalDirectory(Protocol):
    """The one thing the ledger needs to know about animals. Declared here, by
    the consumer, so this package never has to import the animal domain."""

    def exists(self, animal_id: int) -> bool: ...


class DonationRepository(Protocol):
    def add(self, donation: NewDonation) -> Donation: ...

    def get(self, donation_id: int) -> Donation | None: ...

    def list(self, page: PageRequest) -> list[Donation]: ...

    def impact(self) -> ImpactSummary: ...


class DonationService:
    def __init__(
        self,
        repository: DonationRepository,
        animals: AnimalDirectory,
        today: Callable[[], date],
    ) -> None:
        # No default for `today`: whoever builds the service must say which
        # calendar "today" is in, because a UTC server and staff in Amman
        # disagree about it for three hours every night.
        self._repository = repository
        self._animals = animals
        self._today = today

    def record(self, payload: Any) -> Donation:
        """Record a donation. The single way into the ledger: staff-recorded
        cash today, and the verified Stripe webhook later."""
        donation = NewDonation.from_payload(payload, self._today())
        animal_id = donation.earmarked_animal_id
        if animal_id is not None and not self._animals.exists(animal_id):
            raise UnknownEarmarkedAnimal(animal_id)
        return self._repository.add(donation)

    def get(self, donation_id: int) -> Donation:
        donation = self._repository.get(donation_id)
        if donation is None:
            raise DonationNotFound(donation_id)
        return donation

    def list_donations(self, limit: str | None = None, offset: str | None = None) -> list[Donation]:
        return self._repository.list(PageRequest.from_query(limit, offset))

    def impact(self) -> ImpactSummary:
        return self._repository.impact()

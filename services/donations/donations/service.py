"""Business rules for the donation ledger.

The service owns two small interfaces and depends on nothing else: the
DonationRepository it stores through, and the AnimalDirectory it asks whether
an earmarked animal exists. Neither mentions the database or the animal package;
create_app supplies the concrete objects.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from enum import StrEnum
from typing import Any, Protocol

from donations.models import (
    MAX_DONATION_FILS,
    MIN_CHECKOUT_FILS,
    CheckoutRequest,
    CheckoutSession,
    Donation,
    DonationPurpose,
    ImpactSummary,
    NewDonation,
    PageRequest,
    PaymentConfirmed,
    ProviderCharge,
    ValidationError,
)

logger = logging.getLogger(__name__)


class DonationNotFound(LookupError):
    def __init__(self, donation_id: int) -> None:
        super().__init__(f"no donation with id {donation_id}")


class UnknownEarmarkedAnimal(ValidationError):
    """The earmarked animal id does not match any animal. A ValidationError,
    because it is the request that is wrong, so it answers 400 like one."""

    def __init__(self, animal_id: int) -> None:
        super().__init__(f"earmarked_animal_id {animal_id} does not match any animal")


class AnimalsUnavailable(RuntimeError):
    """The animals service could not answer in time: stopped, unreachable, too
    slow, or answering with an error. Raised by an AnimalDirectory; each caller
    below decides what that means for its own request (ADR-6)."""


class PaymentsUnavailable(RuntimeError):
    """Card donations are switched off: keys missing, a live key refused, or no
    valid PUBLIC_BASE_URL. The reason is logged once at startup."""


class InvalidWebhookSignature(ValueError):
    """A webhook call that cannot be proven to come from the payment provider."""


class PaymentProviderError(RuntimeError):
    """The payment provider could not be reached or refused the request."""


class WebhookOutcome(StrEnum):
    """What happened to a verified webhook. Every outcome answers 200, because
    retrying would not change any of them."""

    RECORDED = "recorded"
    ALREADY_RECORDED = "already_recorded"
    IGNORED = "ignored"
    NEEDS_RECONCILIATION = "needs_reconciliation"


class PaymentGateway(Protocol):
    """What the service needs from a card payment provider. Declared here, by
    the consumer; Stripe, or later a regional gateway, conforms to it."""

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession: ...

    def verify_event(self, payload: bytes, signature: str | None) -> PaymentConfirmed | None: ...


class AnimalDirectory(Protocol):
    """The one thing the ledger needs to know about animals. Declared here, by
    the consumer, so this package never has to import the animal domain.

    exists() answers True or False when the animals service gives a definite
    answer, and raises AnimalsUnavailable when it cannot."""

    def exists(self, animal_id: int) -> bool: ...


class DonationRepository(Protocol):
    def add(self, donation: NewDonation) -> Donation: ...

    def get(self, donation_id: int) -> Donation | None: ...

    def list(self, page: PageRequest) -> list[Donation]: ...

    def add_paid(self, donation: NewDonation, charge: ProviderCharge) -> Donation | None: ...

    def impact(self) -> ImpactSummary: ...


class DonationService:
    def __init__(
        self,
        repository: DonationRepository,
        animals: AnimalDirectory,
        today: Callable[[], date],
        gateway: PaymentGateway | None = None,
    ) -> None:
        # No default for `today`: whoever builds the service must say which
        # calendar "today" is in, because a UTC server and staff in Amman
        # disagree about it for three hours every night.
        self._repository = repository
        self._animals = animals
        self._today = today
        # None means card donations are unavailable; see create_app for why.
        self._gateway = gateway

    def record(self, payload: Any) -> Donation:
        """Record a donation staff received in cash or by bank transfer. Card
        donations enter the ledger only through confirm_payment."""
        donation = NewDonation.from_payload(payload, self._today())
        # If the animals service cannot answer, AnimalsUnavailable propagates
        # and staff get a 503 asking them to retry: the ledger is append-only,
        # so an unchecked typo here could never be taken back (ADR-6).
        self._check_earmark(donation.earmarked_animal_id)
        return self._repository.add(donation)

    def start_checkout(self, payload: Any) -> CheckoutSession:
        """Ask the provider for a payment page. Writes nothing to the ledger:
        a donation exists only once the provider confirms the money moved."""
        gateway = self._require_gateway()
        request = CheckoutRequest.from_payload(payload)
        try:
            self._check_earmark(request.earmarked_animal_id)
        except AnimalsUnavailable:
            # A donor is never turned away because another service is down.
            # The earmark goes ahead unverified, and confirm_payment checks it
            # again when the money arrives (ADR-6).
            logger.warning(
                "Checkout earmarked for animal %d went ahead unverified: animals service unavailable",
                request.earmarked_animal_id,
            )
        return gateway.create_checkout(request)

    def handle_webhook(self, payload: bytes, signature: str | None) -> WebhookOutcome:
        """Verify a provider message and record the payment it confirms."""
        confirmed = self._require_gateway().verify_event(payload, signature)
        if confirmed is None:
            return WebhookOutcome.IGNORED
        return self.confirm_payment(confirmed)

    def confirm_payment(self, payment: PaymentConfirmed) -> WebhookOutcome:
        """Record a confirmed payment once, whatever happens next.

        The money has already moved, so nothing here raises: a problem is
        logged for staff (by session id only, never a name) and still answers
        200, because a provider retry could not fix it.
        """
        session_id = payment.charge.session_id
        if payment.amount_fils is None or not (
            MIN_CHECKOUT_FILS <= payment.amount_fils <= MAX_DONATION_FILS
        ):
            logger.error("Payment %s not recorded: unexpected currency or amount; reconcile by hand", session_id)
            return WebhookOutcome.NEEDS_RECONCILIATION
        try:
            purpose = DonationPurpose(payment.purpose)
        except ValueError:
            logger.error("Payment %s not recorded: unknown purpose; reconcile by hand", session_id)
            return WebhookOutcome.NEEDS_RECONCILIATION

        animal_id = payment.earmarked_animal_id
        if animal_id is not None:
            # The donor paid for this animal; keep their intent and let staff
            # follow up, rather than silently moving the gift elsewhere. That
            # holds whether the animal is missing or simply cannot be checked.
            try:
                if not self._animals.exists(animal_id):
                    logger.warning(
                        "Payment %s earmarked for missing animal %d; recorded as given", session_id, animal_id
                    )
            except AnimalsUnavailable:
                logger.warning(
                    "Payment %s earmarked for animal %d recorded unverified: animals service unavailable",
                    session_id,
                    animal_id,
                )

        recorded = self._repository.add_paid(
            NewDonation(
                donor_name=payment.donor_name,
                amount_fils=payment.amount_fils,
                purpose=purpose,
                earmarked_animal_id=animal_id,
                received_on=payment.paid_on,
            ),
            payment.charge,
        )
        return WebhookOutcome.RECORDED if recorded else WebhookOutcome.ALREADY_RECORDED

    def get(self, donation_id: int) -> Donation:
        donation = self._repository.get(donation_id)
        if donation is None:
            raise DonationNotFound(donation_id)
        return donation

    def list_donations(self, limit: str | None = None, offset: str | None = None) -> list[Donation]:
        return self._repository.list(PageRequest.from_query(limit, offset))

    def impact(self) -> ImpactSummary:
        return self._repository.impact()

    def _check_earmark(self, animal_id: int | None) -> None:
        if animal_id is not None and not self._animals.exists(animal_id):
            raise UnknownEarmarkedAnimal(animal_id)

    def _require_gateway(self) -> PaymentGateway:
        if self._gateway is None:
            raise PaymentsUnavailable("card donations are not available")
        return self._gateway

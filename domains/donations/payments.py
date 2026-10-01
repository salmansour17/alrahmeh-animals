"""Stripe, behind the donation service's PaymentGateway interface.

This is the only module in the project that imports `stripe`, and a test
enforces that. It is an Adapter: it turns the Stripe SDK's objects and errors
into the donation domain's own types (CheckoutSession, PaymentConfirmed) and
exceptions, so nothing Stripe-shaped reaches the service. Replacing Stripe with
a regional gateway means writing another class with these two methods (ADR-5).

Currency is part of that translation. The test-mode Stripe account cannot
charge in JOD, so it charges US dollars at the Central Bank of Jordan's fixed
peg (1 USD = 0.709 JOD, unchanged since 1995) and converts the verified amount
back into fils. The domain only ever sees fils. A gateway that charges JOD
directly would need none of this.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, tzinfo
from typing import Any

import stripe

from domains.donations.models import (
    CheckoutRequest,
    CheckoutSession,
    PaymentConfirmed,
    ProviderCharge,
    format_jod,
)
from domains.donations.service import InvalidWebhookSignature, PaymentProviderError

logger = logging.getLogger(__name__)

EVENT_CHECKOUT_COMPLETED = "checkout.session.completed"
PAYMENT_STATUS_PAID = "paid"
MODE_PAYMENT = "payment"
PAYMENT_METHOD_CARD = "card"
PRODUCT_NAME = "Donation to Al-Rahmeh Association for Animals"

# The currency Stripe charges, and the peg used to convert it. 709 fils per
# dollar is the Central Bank of Jordan's fixed rate; 100 cents per dollar.
STRIPE_CURRENCY = "usd"
FILS_PER_USD = 709
CENTS_PER_USD = 100

# Metadata keys. Stripe allows 50 keys of up to 40 characters and values of up
# to 500 characters; the longest value here is a donor name, capped at 120 by
# NewDonation's rules before it can reach this module.
META_PURPOSE = "purpose"
META_EARMARKED_ANIMAL_ID = "earmarked_animal_id"
META_DONOR_NAME = "donor_name"


class StripeGateway:
    """Implements service.PaymentGateway with Stripe Checkout."""

    def __init__(
        self,
        secret_key: str,
        webhook_secret: str,
        success_url: str,
        cancel_url: str,
        local_timezone: tzinfo,
    ) -> None:
        # The key is passed per request rather than set on the global
        # stripe.api_key, so nothing else in the process can pick it up.
        self._secret_key = secret_key
        self._webhook_secret = webhook_secret
        self._success_url = success_url
        self._cancel_url = cancel_url
        self._local_timezone = local_timezone

    def __repr__(self) -> str:
        return "StripeGateway(<secrets hidden>)"

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        metadata = {META_PURPOSE: request.purpose.value}
        if request.earmarked_animal_id is not None:
            metadata[META_EARMARKED_ANIMAL_ID] = str(request.earmarked_animal_id)
        if request.donor_name is not None:
            metadata[META_DONOR_NAME] = request.donor_name

        try:
            session = stripe.checkout.Session.create(
                api_key=self._secret_key,
                mode=MODE_PAYMENT,
                payment_method_types=[PAYMENT_METHOD_CARD],
                # Amount and currency come from our validated request, never
                # from a price id or currency the browser could choose.
                line_items=[
                    {
                        "price_data": {
                            "currency": STRIPE_CURRENCY,
                            "unit_amount": fils_to_cents(request.amount_fils),
                            "product_data": {
                                "name": f"{PRODUCT_NAME} ({format_jod(request.amount_fils)} JOD)"
                            },
                        },
                        "quantity": 1,
                    }
                ],
                metadata=metadata,
                # Adaptive Pricing would let Stripe re-price the donation in the
                # donor's local currency at its own rate; off, so every donor is
                # charged exactly the pegged amount the ledger converts back.
                adaptive_pricing={"enabled": False},
                success_url=self._success_url,
                cancel_url=self._cancel_url,
            )
        except stripe.StripeError as error:
            # Log Stripe's error code only: its message can echo request data.
            logger.error("Stripe refused to create a checkout session (code=%s)", error.code)
            raise PaymentProviderError("the payment provider could not start a checkout") from None
        return CheckoutSession(id=session.id, url=session.url)

    def verify_event(self, payload: bytes, signature: str | None) -> PaymentConfirmed | None:
        """Check the signature over the exact bytes Stripe sent, then translate.

        Returns None for any verified event that is not a paid Checkout session,
        so the caller can acknowledge it and Stripe stops retrying.
        """
        if not signature:
            raise InvalidWebhookSignature("missing Stripe-Signature header")
        try:
            # The default 300-second tolerance rejects a captured message
            # replayed later, even with its original valid signature.
            event = stripe.Webhook.construct_event(payload, signature, self._webhook_secret)
        except (stripe.SignatureVerificationError, ValueError):
            raise InvalidWebhookSignature("webhook signature could not be verified") from None

        if event.type != EVENT_CHECKOUT_COMPLETED:
            return None
        session = event.data.object
        if session.payment_status != PAYMENT_STATUS_PAID:
            return None

        metadata = _metadata(session)
        charge = ProviderCharge(
            session_id=session.id, amount_minor=session.amount_total, currency=session.currency
        )
        return PaymentConfirmed(
            charge=charge,
            # Converted from what Stripe verified it charged, never from what
            # the donor asked for. Any other currency cannot be expressed in
            # fils here, and the service flags it for staff.
            amount_fils=cents_to_fils(charge.amount_minor) if charge.currency == STRIPE_CURRENCY else None,
            purpose=metadata.get(META_PURPOSE),
            earmarked_animal_id=_positive_int_or_none(metadata.get(META_EARMARKED_ANIMAL_ID)),
            donor_name=metadata.get(META_DONOR_NAME),
            paid_on=datetime.fromtimestamp(event.created, timezone.utc)
            .astimezone(self._local_timezone)
            .date(),
        )


def fils_to_cents(amount_fils: int) -> int:
    """JOD fils to US cents at the peg, rounded to the nearest cent."""
    return _round_div(amount_fils * CENTS_PER_USD, FILS_PER_USD)


def cents_to_fils(amount_cents: int) -> int:
    """US cents to JOD fils at the peg, rounded to the nearest fil."""
    return _round_div(amount_cents * FILS_PER_USD, CENTS_PER_USD)


def _round_div(numerator: int, denominator: int) -> int:
    """numerator / denominator rounded half up, in integers: no float ever
    touches money."""
    return (2 * numerator + denominator) // (2 * denominator)


def _metadata(session: Any) -> dict[str, str]:
    # A StripeObject in this SDK version is not a dict and has no .get(), so it
    # is converted once, here, and a plain dict is all the rest of the code sees.
    return session.metadata.to_dict() if session.metadata else {}


def _positive_int_or_none(raw: str | None) -> int | None:
    if raw is None or not raw.isascii() or not raw.isdigit() or int(raw) < 1:
        return None
    return int(raw)

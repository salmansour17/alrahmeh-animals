"""Tests for the real StripeGateway adapter, with no network and no real keys.

A Stripe webhook signature is an HMAC-SHA256 of "<timestamp>.<body>" under the
webhook secret, so a test can produce a genuine one locally with a dummy secret
and run the adapter's real verification code against it. Creating a checkout
does need Stripe's API, so stripe.checkout.Session.create is replaced for those
tests and the arguments it would have sent are checked instead.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from datetime import date, timedelta, timezone

import pytest
import stripe

from domains.donations.models import (
    MAX_DONATION_FILS,
    MIN_CHECKOUT_FILS,
    CheckoutRequest,
    DonationPurpose,
    PaymentConfirmed,
    ProviderCharge,
)
from domains.donations.payments import StripeGateway, cents_to_fils, fils_to_cents
from domains.donations.service import InvalidWebhookSignature, PaymentProviderError

WEBHOOK_SECRET = "whsec_dummy_test_only"
AMMAN = timezone(timedelta(hours=3))
# 2026-09-30 22:30 UTC, which is already 1 October in Amman.
LATE_EVENING_UTC = 1_790_807_400


def gateway() -> StripeGateway:
    return StripeGateway(
        secret_key="sk_test_dummy_test_only",
        webhook_secret=WEBHOOK_SECRET,
        success_url="https://donate.example.org/donate/thanks",
        cancel_url="https://donate.example.org/donate",
        local_timezone=AMMAN,
    )


def sign(payload: bytes, secret: str = WEBHOOK_SECRET, at: int | None = None) -> str:
    timestamp = int(time.time()) if at is None else at
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256)
    return f"t={timestamp},v1={digest.hexdigest()}"


def event(
    *,
    event_type: str = "checkout.session.completed",
    payment_status: str = "paid",
    metadata: dict | None = None,
    session_id: str = "cs_test_1",
    amount_total: int = 3_597,  # USD 35.97, what 25.500 JOD becomes at the peg
    currency: str = "usd",
) -> bytes:
    return json.dumps(
        {
            "id": "evt_test_1",
            "object": "event",
            "type": event_type,
            "created": LATE_EVENING_UTC,
            "data": {
                "object": {
                    "id": session_id,
                    "object": "checkout.session",
                    "amount_total": amount_total,
                    "currency": currency,
                    "payment_status": payment_status,
                    "metadata": {"purpose": "medical_fund"} if metadata is None else metadata,
                }
            },
        }
    ).encode()


# --- verify_event ------------------------------------------------------------


def test_a_signed_paid_session_becomes_our_own_payment_type():
    payload = event(metadata={"purpose": "medical_fund", "earmarked_animal_id": "7", "donor_name": "Um Khaled"})

    confirmed = gateway().verify_event(payload, sign(payload))

    assert confirmed == PaymentConfirmed(
        charge=ProviderCharge(session_id="cs_test_1", amount_minor=3_597, currency="usd"),
        amount_fils=25_503,  # USD 35.97 at 709 fils per dollar, to the nearest fil
        purpose="medical_fund",
        earmarked_animal_id=7,
        donor_name="Um Khaled",
        paid_on=date(2026, 10, 1),  # the event's time, as a date in Amman
    )


def test_a_charge_in_any_other_currency_cannot_be_expressed_in_fils():
    payload = event(currency="eur", amount_total=3_000)
    confirmed = gateway().verify_event(payload, sign(payload))
    assert confirmed.amount_fils is None
    assert confirmed.charge == ProviderCharge(session_id="cs_test_1", amount_minor=3_000, currency="eur")


def test_optional_metadata_may_be_absent():
    payload = event(metadata={"purpose": "general"})
    confirmed = gateway().verify_event(payload, sign(payload))
    assert confirmed.earmarked_animal_id is None
    assert confirmed.donor_name is None


@pytest.mark.parametrize(
    "header",
    [
        None,
        "",
        "t=123,v1=deadbeef",
        "not-a-signature-header",
    ],
    ids=["missing", "empty", "forged", "garbage"],
)
def test_unverifiable_calls_are_rejected(header):
    with pytest.raises(InvalidWebhookSignature):
        gateway().verify_event(event(), header)


def test_a_signature_made_with_another_secret_is_rejected():
    payload = event()
    with pytest.raises(InvalidWebhookSignature):
        gateway().verify_event(payload, sign(payload, secret="whsec_someone_else"))


def test_a_tampered_body_fails_its_original_signature():
    payload = event(amount_total=3_597)
    header = sign(payload)
    tampered = payload.replace(b"3597", b"9597")
    with pytest.raises(InvalidWebhookSignature):
        gateway().verify_event(tampered, header)


def test_an_old_captured_message_is_rejected_even_with_a_valid_signature():
    payload = event()
    ten_minutes_ago = int(time.time()) - 600  # beyond Stripe's 300-second tolerance
    with pytest.raises(InvalidWebhookSignature):
        gateway().verify_event(payload, sign(payload, at=ten_minutes_ago))


def test_a_signed_body_that_is_not_json_is_rejected():
    payload = b"not json"
    with pytest.raises(InvalidWebhookSignature):
        gateway().verify_event(payload, sign(payload))


@pytest.mark.parametrize(
    "payload",
    [event(event_type="payment_intent.created"), event(payment_status="unpaid")],
    ids=["other-event", "unpaid-session"],
)
def test_verified_events_that_are_not_a_paid_checkout_are_ignored(payload):
    assert gateway().verify_event(payload, sign(payload)) is None


# --- create_checkout ---------------------------------------------------------


class _Recorder:
    def __init__(self):
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return stripe.checkout.Session.construct_from(
            {"id": "cs_test_new", "url": "https://checkout.stripe.com/c/pay/cs_test_new"}, None
        )


def test_checkout_is_built_entirely_on_the_server(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(stripe.checkout.Session, "create", recorder)
    request = CheckoutRequest(
        amount_fils=25_500, purpose=DonationPurpose.FOOD_FUND, earmarked_animal_id=7, donor_name="Um Khaled"
    )

    session = gateway().create_checkout(request)

    assert (session.id, session.url) == ("cs_test_new", "https://checkout.stripe.com/c/pay/cs_test_new")
    sent = recorder.kwargs
    assert sent["mode"] == "payment"
    assert sent["payment_method_types"] == ["card"]
    assert sent["adaptive_pricing"] == {"enabled": False}
    price = sent["line_items"][0]["price_data"]
    assert price["currency"] == "usd"
    assert price["unit_amount"] == 3_597  # 25.500 JOD at the peg
    assert price["product_data"]["name"].endswith("(25.500 JOD)")
    assert sent["metadata"] == {"purpose": "food_fund", "earmarked_animal_id": "7", "donor_name": "Um Khaled"}
    assert sent["success_url"] == "https://donate.example.org/donate/thanks"
    assert sent["cancel_url"] == "https://donate.example.org/donate"
    # The key travels with the request, never through the global stripe.api_key.
    assert sent["api_key"] == "sk_test_dummy_test_only"
    assert stripe.api_key is None


def test_optional_fields_are_left_out_of_metadata(monkeypatch):
    recorder = _Recorder()
    monkeypatch.setattr(stripe.checkout.Session, "create", recorder)
    gateway().create_checkout(
        CheckoutRequest(amount_fils=5_000, purpose=DonationPurpose.GENERAL, earmarked_animal_id=None, donor_name=None)
    )
    assert recorder.kwargs["metadata"] == {"purpose": "general"}


def test_a_stripe_failure_becomes_our_own_error(monkeypatch, caplog):
    def refuse(**kwargs):
        raise stripe.InvalidRequestError("Amount must be at least 0.500 jod", param="amount", code="amount_too_small")

    monkeypatch.setattr(stripe.checkout.Session, "create", refuse)
    request = CheckoutRequest(
        amount_fils=5_000, purpose=DonationPurpose.GENERAL, earmarked_animal_id=None, donor_name="Secret Donor"
    )
    with pytest.raises(PaymentProviderError) as raised:
        gateway().create_checkout(request)

    assert raised.value.__cause__ is None  # the Stripe exception is not chained on
    assert "amount_too_small" in caplog.text
    assert "Secret Donor" not in caplog.text


# --- the peg -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("fils", "cents"),
    [(709, 100), (25_500, 3_597), (MIN_CHECKOUT_FILS, 71), (MAX_DONATION_FILS, 1_410_437), (1, 0)],
)
def test_fils_to_cents_at_the_peg(fils, cents):
    assert fils_to_cents(fils) == cents


@pytest.mark.parametrize(("cents", "fils"), [(100, 709), (3_597, 25_503), (1, 7), (50, 355)])
def test_cents_to_fils_at_the_peg(cents, fils):
    assert cents_to_fils(cents) == fils


def test_every_allowed_card_amount_survives_the_round_trip_within_limits():
    """Whatever a donor may ask for, the amount recorded after the trip
    through US cents stays inside the ledger's limits and within half a cent
    (about 3.5 fils) of the request."""
    for fils in list(range(MIN_CHECKOUT_FILS, MIN_CHECKOUT_FILS + 2_000)) + [MAX_DONATION_FILS - n for n in range(2_000)]:
        recorded = cents_to_fils(fils_to_cents(fils))
        assert MIN_CHECKOUT_FILS <= recorded <= MAX_DONATION_FILS
        assert abs(recorded - fils) <= 4


def test_repr_hides_the_secrets():
    assert "dummy" not in repr(gateway())

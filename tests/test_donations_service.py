"""Tests for the donation ledger's business rules.

Like the animal tests, these run against the real SQLite repository on a
temporary database. The one fake is the AnimalDirectory: the ledger must not
depend on the animal domain, so its tests don't either.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from db.connection import SCHEMA_PATH
from domains.donations.models import (
    FILS_PER_JOD,
    MAX_DONATION_FILS,
    CheckoutRequest,
    CheckoutSession,
    DonationPurpose,
    PaymentConfirmed,
    ProviderCharge,
    ValidationError,
    format_jod,
    parse_amount_jod,
)
from domains.donations.repository import SqliteDonationRepository
from domains.donations.service import (
    DonationNotFound,
    DonationService,
    InvalidWebhookSignature,
    PaymentsUnavailable,
    UnknownEarmarkedAnimal,
    WebhookOutcome,
)

P = DonationPurpose
TODAY = date(2026, 9, 30)
KNOWN_ANIMAL = 7


class FakeAnimalDirectory:
    """Stands in for the adapter over AnimalService: an int in, a bool out."""

    def __init__(self, ids: set[int]) -> None:
        self._ids = ids

    def exists(self, animal_id: int) -> bool:
        return animal_id in self._ids


@pytest.fixture
def repository(database) -> SqliteDonationRepository:
    return SqliteDonationRepository(database)


@pytest.fixture
def service(repository) -> DonationService:
    return DonationService(repository, FakeAnimalDirectory({KNOWN_ANIMAL}), today=lambda: TODAY)


def _give(service: DonationService, amount: str, purpose: DonationPurpose = P.GENERAL, **extra):
    return service.record({"amount_jod": amount, "purpose": purpose.value, **extra})


# --- the enum and the schema agree -------------------------------------------


def test_purpose_enum_matches_the_schema_check_constraint():
    schema = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    allowed = re.search(r"CHECK \(purpose IN \(([^)]*)\)\)", schema).group(1)
    in_schema = {value.strip().strip("'") for value in allowed.split(",")}
    assert in_schema == {purpose.value for purpose in DonationPurpose}


# --- amounts -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "fils"),
    [("25.500", 25_500), ("25.5", 25_500), ("25", 25_000), ("0.001", 1), ("00012.34", 12_340)],
)
def test_amounts_convert_to_exact_fils(text, fils):
    assert parse_amount_jod(text) == fils


@pytest.mark.parametrize(
    "bad",
    [
        "1e3", "NaN", "Infinity", "-5", " 5", "5 ", "5.1234", "25.5555", "", ".5", "5.",
        "1,000", "25\n", "٢٥",  # Arabic-Indic "25": \d would have let it through
        "123456",
    ],
)
def test_malformed_amount_strings_are_rejected(bad):
    with pytest.raises(ValidationError, match="digits with at most 3 decimal places"):
        parse_amount_jod(bad)


@pytest.mark.parametrize("bad", [25.5, 25, True, None, ["25"], {"jod": "25"}])
def test_amount_must_be_a_string(bad):
    with pytest.raises(ValidationError, match="must be a string"):
        parse_amount_jod(bad)


@pytest.mark.parametrize("zero", ["0", "0.000", "00.0"])
def test_zero_is_rejected(zero):
    with pytest.raises(ValidationError, match="more than zero"):
        parse_amount_jod(zero)


def test_the_limit_is_inclusive_and_one_fil_over_is_rejected():
    assert parse_amount_jod("10000.000") == MAX_DONATION_FILS
    with pytest.raises(ValidationError, match="at most 10000"):
        parse_amount_jod("10000.001")


@pytest.mark.parametrize(
    ("fils", "text"), [(25_500, "25.500"), (1, "0.001"), (0, "0.000"), (MAX_DONATION_FILS, "10000.000")]
)
def test_format_jod_is_exact(fils, text):
    assert format_jod(fils) == text


def test_format_and_parse_round_trip():
    for fils in (1, 999, FILS_PER_JOD, 123_456, MAX_DONATION_FILS):
        assert parse_amount_jod(format_jod(fils)) == fils


# --- recording ---------------------------------------------------------------


def test_recorded_donation_round_trips(service):
    donation = _give(service, "25.500", P.MEDICAL_FUND, donor_name="  Um Khaled  ")

    assert donation.amount_fils == 25_500
    assert donation.donor_name == "Um Khaled"
    assert donation.received_on == TODAY
    assert service.get(donation.id) == donation


def test_received_on_can_be_backdated_but_not_future(service):
    assert _give(service, "5", received_on="2026-09-25").received_on == date(2026, 9, 25)
    assert _give(service, "5", received_on=TODAY.isoformat()).received_on == TODAY
    with pytest.raises(ValidationError, match="future"):
        _give(service, "5", received_on="2026-10-01")


def test_blank_donor_name_is_anonymous(service):
    assert _give(service, "5", donor_name="   ").donor_name is None


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        (None, "JSON object"),
        ({"purpose": "general"}, "missing field(s): amount_jod"),
        ({"amount_jod": "5"}, "missing field(s): purpose"),
        ({"amount_jod": "5", "purpose": "general", "note": "hi"}, "unknown field(s): note"),
        ({"amount_jod": "5", "purpose": "vet_bills"}, "purpose must be one of"),
        ({"amount_jod": "5", "purpose": "general", "donor_name": "x" * 121}, "at most 120"),
        ({"amount_jod": "5", "purpose": "general", "donor_name": 42}, "donor_name must be a string"),
        ({"amount_jod": "5", "purpose": "general", "earmarked_animal_id": True}, "positive integer"),
        ({"amount_jod": "5", "purpose": "general", "earmarked_animal_id": "7"}, "positive integer"),
        ({"amount_jod": "5", "purpose": "general", "earmarked_animal_id": 0}, "positive integer"),
        ({"amount_jod": "5", "purpose": "general", "received_on": "30/09/2026"}, "ISO date"),
        ({"amount_jod": "5", "purpose": "general", "received_on": 20260930}, "ISO date string"),
    ],
)
def test_invalid_donation_is_rejected(service, payload, complaint):
    with pytest.raises(ValidationError, match=re.escape(complaint)):
        service.record(payload)
    assert service.impact().donation_count == 0


def test_earmark_to_a_known_animal_is_accepted(service):
    assert _give(service, "40", P.MEDICAL_FUND, earmarked_animal_id=KNOWN_ANIMAL).earmarked_animal_id == KNOWN_ANIMAL


def test_earmark_to_a_missing_animal_is_rejected(service):
    with pytest.raises(UnknownEarmarkedAnimal, match="999"):
        _give(service, "40", P.MEDICAL_FUND, earmarked_animal_id=999)
    assert service.impact().donation_count == 0


def test_unknown_donation_raises_not_found(service):
    with pytest.raises(DonationNotFound, match="999"):
        service.get(999)


# --- append-only -------------------------------------------------------------


def test_repository_has_no_way_to_change_or_remove_a_donation():
    mutators = [
        name
        for name in dir(SqliteDonationRepository)
        if name.startswith(("update", "delete", "remove", "edit", "set", "change"))
    ]
    assert mutators == []


@pytest.mark.parametrize(
    "statement",
    ["UPDATE donations SET amount_fils = 1 WHERE id = ?", "DELETE FROM donations WHERE id = ?"],
)
def test_the_database_itself_refuses_to_change_a_donation(service, database, statement):
    donation = _give(service, "25")
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        with database.unit_of_work() as connection:
            connection.execute(statement, (donation.id,))
    assert service.get(donation.id) == donation


# --- impact ------------------------------------------------------------------


def test_impact_on_an_empty_ledger_is_all_zeros(service):
    impact = service.impact()

    assert impact.total_raised_fils == 0
    assert impact.donation_count == 0
    assert impact.animals_helped == 0
    assert impact.totals_by_purpose_fils == {P.MEDICAL_FUND: 0, P.FOOD_FUND: 0, P.GENERAL: 0}


def test_impact_on_a_mixed_ledger(service):
    _give(service, "25.500", P.MEDICAL_FUND, earmarked_animal_id=KNOWN_ANIMAL)
    _give(service, "10", P.MEDICAL_FUND, earmarked_animal_id=KNOWN_ANIMAL)  # same animal again
    _give(service, "4.250", P.FOOD_FUND)
    _give(service, "0.001", P.MEDICAL_FUND)

    impact = service.impact()

    assert impact.total_raised_fils == 25_500 + 10_000 + 4_250 + 1
    assert impact.donation_count == 4
    # Two gifts to the same animal count as one animal helped.
    assert impact.animals_helped == 1
    assert impact.totals_by_purpose_fils == {
        P.MEDICAL_FUND: 35_501,
        P.FOOD_FUND: 4_250,
        P.GENERAL: 0,
    }
    assert sum(impact.totals_by_purpose_fils.values()) == impact.total_raised_fils


# --- the staff list ----------------------------------------------------------


def test_list_is_newest_first_and_paginated(service):
    older = _give(service, "1", received_on="2026-09-01")
    newer = _give(service, "2", received_on="2026-09-20")
    newest = _give(service, "3")

    assert [d.id for d in service.list_donations()] == [newest.id, newer.id, older.id]
    assert [d.id for d in service.list_donations(limit="2")] == [newest.id, newer.id]
    assert [d.id for d in service.list_donations(limit="2", offset="2")] == [older.id]


@pytest.mark.parametrize(
    ("limit", "offset", "complaint"),
    [
        ("0", None, "limit must be between 1 and 200"),
        ("201", None, "limit must be between 1 and 200"),
        ("-1", None, "limit must be a whole number"),
        ("ten", None, "limit must be a whole number"),
        (None, "-5", "offset must be a whole number"),
        (None, "٥", "offset must be a whole number"),  # Arabic-Indic 5
    ],
)
def test_bad_pagination_is_rejected(service, limit, offset, complaint):
    with pytest.raises(ValidationError, match=complaint):
        service.list_donations(limit=limit, offset=offset)


# --- card payments through a gateway -----------------------------------------


class FakeGateway:
    """Stands in for StripeGateway: same types in, same types out, same
    exceptions. It treats the payload as the event itself and the signature
    as valid only if it is the word "valid"."""

    def __init__(self) -> None:
        self.checkouts: list[CheckoutRequest] = []

    def create_checkout(self, request: CheckoutRequest) -> CheckoutSession:
        self.checkouts.append(request)
        return CheckoutSession(id=f"cs_fake_{len(self.checkouts)}", url="https://pay.example/fake")

    def verify_event(self, payload, signature):
        if signature != "valid":
            raise InvalidWebhookSignature("fake gateway: bad signature")
        return payload


def _paid(**overrides) -> PaymentConfirmed:
    fields = dict(
        charge=ProviderCharge(session_id="cs_fake_1", amount_minor=3_597, currency="usd"),
        amount_fils=25_500,
        purpose="medical_fund",
        earmarked_animal_id=None,
        donor_name=None,
        paid_on=TODAY,
    )
    return PaymentConfirmed(**{**fields, **overrides})


@pytest.fixture
def gateway() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def paying_service(repository, gateway) -> DonationService:
    return DonationService(
        repository, FakeAnimalDirectory({KNOWN_ANIMAL}), today=lambda: TODAY, gateway=gateway
    )


def test_checkout_asks_the_gateway_and_writes_nothing(paying_service, gateway):
    session = paying_service.start_checkout({"amount_jod": "25.500", "purpose": "food_fund", "donor_name": "Um Khaled"})

    assert session.url == "https://pay.example/fake"
    assert gateway.checkouts == [
        CheckoutRequest(amount_fils=25_500, purpose=P.FOOD_FUND, earmarked_animal_id=None, donor_name="Um Khaled")
    ]
    assert paying_service.impact().donation_count == 0


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        ({"amount_jod": "0.499", "purpose": "general"}, "at least 0.500"),
        ({"amount_jod": 25.5, "purpose": "general"}, "must be a string"),
        ({"amount_jod": "10000.010", "purpose": "general"}, "at most 10000"),
        ({"amount_jod": "5", "purpose": "general", "received_on": "2026-09-30"}, "unknown field(s): received_on"),
        ({"amount_jod": "5", "purpose": "general", "currency": "usd"}, "unknown field(s): currency"),
    ],
)
def test_invalid_checkout_never_reaches_the_gateway(paying_service, gateway, payload, complaint):
    with pytest.raises(ValidationError, match=re.escape(complaint)):
        paying_service.start_checkout(payload)
    assert gateway.checkouts == []


def test_checkout_accepts_any_fils_amount_at_or_above_the_minimum(paying_service, gateway):
    paying_service.start_checkout({"amount_jod": "0.500", "purpose": "general"})
    paying_service.start_checkout({"amount_jod": "25.505", "purpose": "general"})
    assert [c.amount_fils for c in gateway.checkouts] == [500, 25_505]


def test_checkout_for_a_missing_animal_is_refused_before_payment(paying_service, gateway):
    with pytest.raises(UnknownEarmarkedAnimal):
        paying_service.start_checkout({"amount_jod": "5", "purpose": "medical_fund", "earmarked_animal_id": 999})
    assert gateway.checkouts == []


def test_without_a_gateway_card_payments_are_unavailable(service):
    with pytest.raises(PaymentsUnavailable):
        service.start_checkout({"amount_jod": "5", "purpose": "general"})
    with pytest.raises(PaymentsUnavailable):
        service.handle_webhook(b"{}", "valid")


def test_a_confirmed_payment_is_recorded_with_the_confirmed_amount(paying_service):
    outcome = paying_service.handle_webhook(_paid(amount_fils=40_000, earmarked_animal_id=KNOWN_ANIMAL), "valid")

    assert outcome is WebhookOutcome.RECORDED
    [donation] = paying_service.list_donations()
    assert donation.amount_fils == 40_000
    assert donation.purpose is P.MEDICAL_FUND
    assert donation.earmarked_animal_id == KNOWN_ANIMAL
    assert donation.received_on == TODAY


def test_a_replayed_payment_is_recorded_once(paying_service):
    assert paying_service.handle_webhook(_paid(), "valid") is WebhookOutcome.RECORDED
    assert paying_service.handle_webhook(_paid(), "valid") is WebhookOutcome.ALREADY_RECORDED

    impact = paying_service.impact()
    assert impact.donation_count == 1
    assert impact.total_raised_fils == 25_500


def test_verified_events_that_need_nothing_are_ignored(paying_service):
    assert paying_service.handle_webhook(None, "valid") is WebhookOutcome.IGNORED
    assert paying_service.impact().donation_count == 0


def test_a_bad_signature_is_refused_and_writes_nothing(paying_service):
    with pytest.raises(InvalidWebhookSignature):
        paying_service.handle_webhook(_paid(), "forged")
    assert paying_service.impact().donation_count == 0


@pytest.mark.parametrize(
    "payment",
    [
        _paid(amount_fils=None),
        _paid(amount_fils=MAX_DONATION_FILS + 10),
        _paid(amount_fils=10),
        _paid(purpose="vet_bills"),
        _paid(purpose=None),
    ],
    ids=["wrong-currency", "over-max", "under-min", "unknown-purpose", "no-purpose"],
)
def test_payments_that_cannot_be_trusted_into_the_ledger_are_flagged_not_recorded(paying_service, payment, caplog):
    """Gap B: money has moved, so this answers 200, but a charge the gateway
    could not express in fils, or an impossible figure, must not enter a SUM
    counted in JOD fils."""
    assert paying_service.confirm_payment(payment) is WebhookOutcome.NEEDS_RECONCILIATION
    assert paying_service.impact().donation_count == 0
    assert "cs_fake_1" in caplog.text


def test_a_gift_for_an_animal_that_has_gone_is_still_recorded_as_given(paying_service, caplog):
    """Gap A: the donor paid for that animal; keep their intent and warn."""
    outcome = paying_service.confirm_payment(_paid(earmarked_animal_id=999, donor_name="Secret Donor"))

    assert outcome is WebhookOutcome.RECORDED
    assert paying_service.list_donations()[0].earmarked_animal_id == 999
    assert "999" in caplog.text
    assert "Secret Donor" not in caplog.text


def test_the_provider_charge_is_kept_beside_the_ledger_row(paying_service, database):
    """The audit trail for the conversion: what Stripe charged, in its own
    currency, next to the fils the ledger recorded."""
    paying_service.confirm_payment(_paid())
    with database.unit_of_work() as connection:
        row = connection.execute(
            "SELECT p.session_id, p.charged_amount_minor, p.charged_currency, d.amount_fils "
            "FROM stripe_payments p JOIN donations d ON d.id = p.donation_id"
        ).fetchone()
    assert tuple(row) == ("cs_fake_1", 3_597, "usd", 25_500)

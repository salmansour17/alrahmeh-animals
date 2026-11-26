"""Reversals: correcting the append-only ledger by adding a row, never by
editing one. Against the real test SQL Server, like the other ledger tests."""

from __future__ import annotations

import threading

import pytest

from donations.models import (
    DonationKind,
    DonationPurpose,
    LedgerSum,
    ProviderCharge,
    ReversalOutcome,
    ValidationError,
    net_impact,
)
from donations.service import AlreadyReversed, DonationNotFound, NotReversible
from tests.test_donations_routes import STAFF
from tests.test_donations_service import KNOWN_ANIMAL, TODAY, repository, service  # noqa: F401 (fixtures)

P = DonationPurpose
K = DonationKind
REASON = {"reason": "Recorded twice by mistake"}


def _give(service, amount: str, purpose: DonationPurpose = P.GENERAL, **extra):  # noqa: F811 (the parameter shadows the fixture)
    return service.record({"amount_jod": amount, "purpose": purpose.value, **extra})


# --- the rules ------------------------------------------------------------------


def test_a_reversal_copies_the_gift_from_the_database(service):  # noqa: F811
    gift = _give(service, "25.500", P.MEDICAL_FUND, donor_name="Mo", earmarked_animal_id=KNOWN_ANIMAL)
    reversal = service.reverse(gift.id, {"reason": "  Recorded twice by mistake  "})

    assert reversal.kind is K.REVERSAL
    assert reversal.reverses_donation_id == gift.id
    assert reversal.reversal_reason == "Recorded twice by mistake"  # trimmed
    assert (reversal.amount_fils, reversal.purpose, reversal.earmarked_animal_id) == (25_500, P.MEDICAL_FUND, 7)
    assert reversal.received_on == TODAY  # the day it was recorded
    assert reversal.donor_name is None  # the gift keeps the name; the reversal links to it
    assert not reversal.reversible

    gift_now = service.get(gift.id)
    assert gift_now.reversed_by_id == reversal.id
    assert not gift_now.reversible
    # The gift itself is unchanged: only the new row says it is reversed.
    assert (gift_now.kind, gift_now.amount_fils, gift_now.donor_name) == (K.GIFT, 25_500, "Mo")


def test_the_request_cannot_choose_the_amount(service):  # noqa: F811
    gift = _give(service, "10")
    with pytest.raises(ValidationError, match="unknown field"):
        service.reverse(gift.id, {"reason": "x", "amount_jod": "1"})


def test_a_gift_can_be_reversed_once(service):  # noqa: F811
    gift = _give(service, "10")
    service.reverse(gift.id, REASON)
    with pytest.raises(AlreadyReversed):
        service.reverse(gift.id, REASON)


def test_a_reversal_cannot_be_reversed(service):  # noqa: F811
    reversal = service.reverse(_give(service, "10").id, REASON)
    with pytest.raises(NotReversible):
        service.reverse(reversal.id, REASON)


def test_an_unknown_donation_cannot_be_reversed(service):  # noqa: F811
    with pytest.raises(DonationNotFound):
        service.reverse(999, REASON)


def test_a_card_donation_can_be_reversed_in_the_ledger(repository, service):  # noqa: F811
    # A ledger entry only: nothing is refunded at the payment provider.
    from donations.models import NewDonation

    paid = repository.add_paid(
        NewDonation(None, 5_000, P.GENERAL, None, TODAY), ProviderCharge("cs_test_CANARY_VALUE", 700, "usd")
    )
    assert service.reverse(paid.id, REASON).reverses_donation_id == paid.id


@pytest.mark.parametrize(
    ("payload", "complaint"),
    [
        ({}, "missing field"),
        ({"reason": ""}, "reason must say why"),
        ({"reason": "   "}, "reason must say why"),
        ({"reason": None}, "reason must say why"),
        ({"reason": 5}, "must be a string"),
        ({"reason": "x" * 501}, "at most 500"),
        ("a reason", "JSON object"),
        (None, "JSON object"),
    ],
)
def test_a_reason_is_required(service, payload, complaint):  # noqa: F811
    gift = _give(service, "10")
    with pytest.raises(ValidationError, match=complaint):
        service.reverse(gift.id, payload)
    assert service.get(gift.id).reversible  # nothing was written


def test_a_reason_in_arabic_is_kept_as_written(service):  # noqa: F811
    reason = "سُجّل مرتين بالخطأ"
    reversal = service.reverse(_give(service, "10").id, {"reason": reason})
    assert service.get(reversal.id).reversal_reason == reason


def test_two_staff_reversing_at_the_same_moment_get_one_reversal(repository, service):  # noqa: F811
    gift = _give(service, "10")
    start = threading.Barrier(2)
    outcomes: list[ReversalOutcome] = []

    def reverse() -> None:
        start.wait()
        outcome, _ = repository.reverse(gift.id, "double click", TODAY)
        outcomes.append(outcome)

    threads = [threading.Thread(target=reverse) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == sorted([ReversalOutcome.REVERSED, ReversalOutcome.ALREADY_REVERSED])
    assert [d.kind for d in service.list_donations()].count(K.REVERSAL) == 1


# --- the counters ---------------------------------------------------------------


def test_the_impact_figures_drop_a_reversed_gift_entirely(service):  # noqa: F811
    keep = _give(service, "65", P.FOOD_FUND)
    wrong = _give(service, "255", P.MEDICAL_FUND, earmarked_animal_id=KNOWN_ANIMAL)
    _give(service, "25", P.MEDICAL_FUND)
    before = service.impact()
    assert (before.total_raised_fils, before.donation_count, before.animals_helped) == (345_000, 3, 1)

    service.reverse(wrong.id, REASON)
    after = service.impact()
    assert after.total_raised_fils == 90_000
    assert after.donation_count == 2  # the reversed gift is gone, the reversal is not a gift
    assert after.animals_helped == 0  # the only earmarked gift was reversed
    assert after.totals_by_purpose_fils == {P.FOOD_FUND: 65_000, P.MEDICAL_FUND: 25_000, P.GENERAL: 0}
    assert service.get(keep.id).reversible


def test_an_animal_still_helped_by_another_gift_stays_counted(service):  # noqa: F811
    first = _give(service, "10", earmarked_animal_id=KNOWN_ANIMAL)
    _give(service, "20", earmarked_animal_id=KNOWN_ANIMAL)
    service.reverse(first.id, REASON)
    assert service.impact().animals_helped == 1


def test_the_list_shows_both_rows_newest_first(service):  # noqa: F811
    gift = _give(service, "10", received_on="2026-09-01")
    reversal = service.reverse(gift.id, REASON)
    assert [(d.id, d.kind) for d in service.list_donations()] == [(reversal.id, K.REVERSAL), (gift.id, K.GIFT)]


def test_net_impact_subtracts_reversals_and_never_counts_them_as_gifts():
    summary = net_impact(
        [
            LedgerSum(P.MEDICAL_FUND, K.GIFT, 280_000, 2),
            LedgerSum(P.MEDICAL_FUND, K.REVERSAL, 255_000, 1),
            LedgerSum(P.FOOD_FUND, K.GIFT, 65_000, 1),
        ],
        animals_helped=0,
    )
    assert summary.totals_by_purpose_fils == {P.MEDICAL_FUND: 25_000, P.FOOD_FUND: 65_000, P.GENERAL: 0}
    assert (summary.total_raised_fils, summary.donation_count, summary.animals_helped) == (90_000, 2, 0)


def test_net_impact_of_an_empty_ledger_is_all_zero():
    summary = net_impact([], animals_helped=0)
    assert (summary.total_raised_fils, summary.donation_count) == (0, 0)
    assert set(summary.totals_by_purpose_fils.values()) == {0}


# --- over HTTP ------------------------------------------------------------------


def _record(client, amount: str = "25.500") -> int:
    body = {"amount_jod": amount, "purpose": "medical_fund", "donor_name": "Mo"}
    return client.post("/api/donations", json=body, headers=STAFF).get_json()["id"]


def test_reversing_over_http(client):
    gift_id = _record(client)
    response = client.post(f"/api/donations/{gift_id}/reversal", json=REASON, headers=STAFF)
    assert response.status_code == 201
    body = response.get_json()
    assert body["kind"] == "reversal"
    assert body["reverses_donation_id"] == gift_id
    assert body["amount_jod"] == "25.500"
    assert body["reversal_reason"] == REASON["reason"]
    assert body["reversible"] is False

    gift = client.get(f"/api/donations/{gift_id}", headers=STAFF).get_json()
    assert (gift["kind"], gift["reversed_by_id"], gift["reversible"]) == ("gift", body["id"], False)
    impact = client.get("/api/donations/impact").get_json()
    assert (impact["total_raised"]["amount_jod"], impact["donation_count"]) == ("0.000", 0)


def test_http_errors(client):
    gift_id = _record(client)
    reversal_id = client.post(f"/api/donations/{gift_id}/reversal", json=REASON, headers=STAFF).get_json()["id"]

    twice = client.post(f"/api/donations/{gift_id}/reversal", json=REASON, headers=STAFF)
    assert (twice.status_code, twice.get_json()["error"]) == (409, "already_reversed")
    of_reversal = client.post(f"/api/donations/{reversal_id}/reversal", json=REASON, headers=STAFF)
    assert (of_reversal.status_code, of_reversal.get_json()["error"]) == (409, "not_reversible")
    unknown = client.post("/api/donations/999/reversal", json=REASON, headers=STAFF)
    assert (unknown.status_code, unknown.get_json()["error"]) == (404, "not_found")
    no_reason = client.post(f"/api/donations/{_record(client)}/reversal", json={}, headers=STAFF)
    assert (no_reason.status_code, no_reason.get_json()["error"]) == (400, "validation_failed")


def test_only_staff_can_reverse(client):
    gift_id = _record(client)
    response = client.post(f"/api/donations/{gift_id}/reversal", json=REASON)
    assert response.status_code == 401
    assert client.get(f"/api/donations/{gift_id}", headers=STAFF).get_json()["reversible"] is True


def test_the_database_refuses_a_reversal_without_a_reason_even_if_the_code_forgets(repository, service):  # noqa: F811
    from db import IntegrityError

    gift = _give(service, "10")
    with pytest.raises(IntegrityError) as raised:
        repository.reverse(gift.id, None, TODAY)  # type: ignore[arg-type]
    assert "ck_donations_reversal_shape" in str(raised.value)
    assert service.get(gift.id).reversible

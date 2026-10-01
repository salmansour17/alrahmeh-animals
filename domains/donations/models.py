"""Entities, enums and input parsing for the donation and impact ledger.

Money is an integer count of fils everywhere in this package (1 JOD = 1000
fils); every name that holds money ends in `_fils`. A float never touches an
amount: the API takes JOD as a string, which is checked character by character
before Decimal converts it, and the JSON output is built with integer division.

The field helpers at the bottom are near-copies of the ones in
domains/animals/models.py. That duplication is deliberate: importing them would
make the ledger depend on the animal package, and ADR-2 forbids that.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any, Mapping

FILS_PER_JOD = 1000
JOD_DECIMAL_PLACES = 3
MAX_DONATION_JOD = 10_000
MAX_DONATION_FILS = MAX_DONATION_JOD * FILS_PER_JOD
# Five integer digits is looser than the maximum on purpose: the pattern only
# decides whether the text is a well-formed amount; the limit is a separate
# rule with its own error message.
_MAX_JOD_DIGITS = 5
# [0-9] rather than \d: \d also matches Arabic-Indic digits, which Decimal
# would happily convert. fullmatch rather than match + $: $ allows a trailing
# newline.
_AMOUNT_JOD = re.compile(
    rf"[0-9]{{1,{_MAX_JOD_DIGITS}}}(\.[0-9]{{1,{JOD_DECIMAL_PLACES}}})?"
)

DONOR_NAME_MAX = 120

# Smallest card donation. The test-mode Stripe account settles in EUR and
# refuses any charge worth less than EUR 0.50 (confirmed 2026-10-01: "must
# convert to at least 50 cents"). 0.500 JOD is about USD 0.71, a margin that
# survives normal EUR/USD movement while staying a round figure for donors.
MIN_CHECKOUT_FILS = 500
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200


class DonationPurpose(StrEnum):
    """What a donation is for. Values match the CHECK constraint on
    donations.purpose; a test compares the two."""

    MEDICAL_FUND = "medical_fund"
    FOOD_FUND = "food_fund"
    GENERAL = "general"


class ValidationError(ValueError):
    """A request body or query parameter that cannot become a domain object."""


@dataclass(frozen=True)
class Donation:
    id: int
    donor_name: str | None
    amount_fils: int
    purpose: DonationPurpose
    earmarked_animal_id: int | None
    received_on: date


@dataclass(frozen=True)
class NewDonation:
    """A donation being recorded: everything except the id."""

    donor_name: str | None
    amount_fils: int
    purpose: DonationPurpose
    earmarked_animal_id: int | None
    received_on: date

    @classmethod
    def from_payload(cls, payload: Any, today: date) -> NewDonation:
        fields = _fields(
            payload,
            required={"amount_jod", "purpose"},
            optional={"donor_name", "earmarked_animal_id", "received_on"},
        )
        received = fields.get("received_on")
        return cls(
            donor_name=_optional_text(fields, "donor_name", DONOR_NAME_MAX),
            amount_fils=parse_amount_jod(fields["amount_jod"]),
            purpose=_enum(fields, "purpose", DonationPurpose),
            earmarked_animal_id=_optional_positive_int(fields, "earmarked_animal_id"),
            received_on=today if received is None else _past_date(fields, "received_on", today),
        )


@dataclass(frozen=True)
class CheckoutRequest:
    """A donor asking to pay by card. Validated with the same helpers as a
    staff-recorded donation, plus the provider's own limits. There is no
    received_on: a card payment is dated by the provider when it happens."""

    amount_fils: int
    purpose: DonationPurpose
    earmarked_animal_id: int | None
    donor_name: str | None

    @classmethod
    def from_payload(cls, payload: Any) -> CheckoutRequest:
        fields = _fields(
            payload,
            required={"amount_jod", "purpose"},
            optional={"donor_name", "earmarked_animal_id"},
        )
        amount_fils = parse_amount_jod(fields["amount_jod"])
        if amount_fils < MIN_CHECKOUT_FILS:
            raise ValidationError(f"card donations must be at least {format_jod(MIN_CHECKOUT_FILS)} JOD")
        return cls(
            amount_fils=amount_fils,
            purpose=_enum(fields, "purpose", DonationPurpose),
            earmarked_animal_id=_optional_positive_int(fields, "earmarked_animal_id"),
            donor_name=_optional_text(fields, "donor_name", DONOR_NAME_MAX),
        )


@dataclass(frozen=True)
class CheckoutSession:
    """What the donor's browser needs: where to go to pay."""

    id: str
    url: str


@dataclass(frozen=True)
class ProviderCharge:
    """What the payment provider actually charged, in its own currency and
    minor unit (US cents for Stripe in test mode). Kept beside the ledger row
    as the audit trail for the conversion into fils."""

    session_id: str
    amount_minor: int
    currency: str


@dataclass(frozen=True)
class PaymentConfirmed:
    """A payment the provider has confirmed, in our own terms. Built only from
    a verified provider message.

    amount_fils is the charge expressed in JOD fils by the gateway, or None if
    the gateway could not express it (an unexpected currency). Purpose stays a
    string: it is checked by the service like any other input, not trusted
    because it came back."""

    charge: ProviderCharge
    amount_fils: int | None
    purpose: str | None
    earmarked_animal_id: int | None
    donor_name: str | None
    paid_on: date


@dataclass(frozen=True)
class ImpactSummary:
    """The homepage figures, all derived from the ledger at request time."""

    total_raised_fils: int
    donation_count: int
    totals_by_purpose_fils: dict[DonationPurpose, int]
    animals_helped: int


@dataclass(frozen=True)
class PageRequest:
    """Bounds for the staff donation list, so it can never return everything."""

    limit: int
    offset: int

    @classmethod
    def from_query(cls, limit: str | None, offset: str | None) -> PageRequest:
        page_size = _query_int("limit", limit, DEFAULT_PAGE_SIZE)
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        return cls(limit=page_size, offset=_query_int("offset", offset, 0))


def parse_amount_jod(value: Any) -> int:
    """Turn "25.500" into 25500 fils, rejecting anything that is not exactly a
    positive JOD amount written as a string."""
    if not isinstance(value, str):
        raise ValidationError('amount_jod must be a string, e.g. "25.500"')
    if not _AMOUNT_JOD.fullmatch(value):
        raise ValidationError(
            f"amount_jod must be digits with at most {JOD_DECIMAL_PLACES} decimal places, "
            'e.g. "25.500"'
        )
    amount_fils = int(Decimal(value) * FILS_PER_JOD)
    if amount_fils <= 0:
        raise ValidationError("amount_jod must be more than zero")
    if amount_fils > MAX_DONATION_FILS:
        raise ValidationError(f"amount_jod must be at most {MAX_DONATION_JOD}")
    return amount_fils


def format_jod(amount_fils: int) -> str:
    """25500 -> "25.500". Integer arithmetic only, so no rounding can creep in."""
    return f"{amount_fils // FILS_PER_JOD}.{amount_fils % FILS_PER_JOD:0{JOD_DECIMAL_PLACES}d}"


# --- field helpers (duplicated from the animals domain; see module docstring) --


def _fields(payload: Any, required: set[str], optional: set[str]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValidationError("request body must be a JSON object")
    unknown = sorted(set(payload) - required - optional)
    if unknown:
        raise ValidationError(f"unknown field(s): {', '.join(unknown)}")
    missing = sorted(required - set(payload))
    if missing:
        raise ValidationError(f"missing field(s): {', '.join(missing)}")
    return payload


def _optional_text(fields: Mapping[str, Any], name: str, max_length: int) -> str | None:
    value = fields.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a string")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"{name} must be at most {max_length} characters")
    return value or None


def _optional_positive_int(fields: Mapping[str, Any], name: str) -> int | None:
    value = fields.get(name)
    if value is None:
        return None
    # bool is a subclass of int in Python, so True would otherwise pass as 1.
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValidationError(f"{name} must be a positive integer")
    return value


def _past_date(fields: Mapping[str, Any], name: str, today: date) -> date:
    value = fields[name]
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be an ISO date string, e.g. 2026-09-30")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValidationError(f"{name} must be an ISO date, e.g. 2026-09-30") from None
    if parsed > today:
        raise ValidationError(f"{name} cannot be in the future")
    return parsed


def _enum(fields: Mapping[str, Any], name: str, enum_type: type[StrEnum]) -> Any:
    try:
        return enum_type(fields[name])
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValidationError(f"{name} must be one of: {allowed}") from None


def _query_int(name: str, raw: str | None, default: int) -> int:
    """A non-negative whole number from a query string. ASCII digits only, so a
    minus sign or an Arabic-Indic digit is rejected rather than converted."""
    if raw is None:
        return default
    if not raw.isascii() or not raw.isdigit():
        raise ValidationError(f"{name} must be a whole number")
    return int(raw)

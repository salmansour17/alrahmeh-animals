"""Entities and input parsing for enquiries.

The field helpers at the bottom are copies of the ones in the animal domain's
models. Importing them would make this domain depend on that one, which ADR-2
forbids, so a few small functions are duplicated instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

NAME_MAX = 120
EMAIL_MAX = 254  # the longest address the email standards allow
SUBJECT_MAX = 150
MESSAGE_MAX = 4000
DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

# A field people never see on the form. Bots fill in every field they find.
HONEYPOT_FIELD = "website"


class Topic(StrEnum):
    """What the message is about. Values match the CHECK constraint on
    enquiries.topic."""

    VOLUNTEER = "volunteer"
    QUESTION = "question"
    SHOP_ORDER = "shop_order"
    OTHER = "other"


class ValidationError(ValueError):
    """A request body or query parameter that cannot become a domain object."""


@dataclass(frozen=True)
class Enquiry:
    """A message from the public. Personal data: staff-only, never logged."""

    id: int
    topic: Topic
    name: str
    email: str
    subject: str
    message: str
    handled: bool
    received_at: str


@dataclass(frozen=True)
class NewEnquiry:
    topic: Topic
    name: str
    email: str
    subject: str
    message: str

    @classmethod
    def from_payload(cls, payload: Any) -> NewEnquiry:
        fields = _fields(
            payload,
            required={"topic", "name", "email", "subject", "message"},
            optional={HONEYPOT_FIELD},
        )
        return cls(
            topic=_enum(fields, "topic", Topic),
            name=_text(fields, "name", NAME_MAX),
            email=_email(fields, "email"),
            subject=_text(fields, "subject", SUBJECT_MAX),
            message=_text(fields, "message", MESSAGE_MAX),
        )


@dataclass(frozen=True)
class EnquiryFilter:
    """Which messages the staff list shows, and how many at a time."""

    handled: bool | None
    limit: int
    offset: int

    @classmethod
    def from_query(cls, handled: str | None, limit: str | None, offset: str | None) -> EnquiryFilter:
        if handled not in (None, "true", "false"):
            raise ValidationError("handled must be true or false")
        page_size = _query_int("limit", limit, DEFAULT_PAGE_SIZE)
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValidationError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        return cls(
            handled=None if handled is None else handled == "true",
            limit=page_size,
            offset=_query_int("offset", offset, 0),
        )


def is_honeypot(payload: Any) -> bool:
    """True if the hidden field was filled in, which only bots do. Checked
    before validation, so a bot learns nothing from the answer."""
    return isinstance(payload, Mapping) and bool(payload.get(HONEYPOT_FIELD))


# --- field helpers (copied from the animal domain; see module docstring) ------


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


def _text(fields: Mapping[str, Any], name: str, max_length: int) -> str:
    value = fields[name]
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    value = value.strip()
    if len(value) > max_length:
        raise ValidationError(f"{name} must be at most {max_length} characters")
    return value


def _email(fields: Mapping[str, Any], name: str) -> str:
    """A basic shape check; the message never repeats the value."""
    value = _text(fields, name, EMAIL_MAX)
    local, at, domain = value.rpartition("@")
    if (
        not at
        or not local
        or "@" in local
        or any(ch.isspace() for ch in value)
        or "." not in domain
        or domain.startswith(".")
        or domain.endswith(".")
    ):
        raise ValidationError(f"{name} must look like name@example.org")
    return value


def _enum(fields: Mapping[str, Any], name: str, enum_type: type[StrEnum]) -> Any:
    try:
        return enum_type(fields[name])
    except ValueError:
        allowed = ", ".join(member.value for member in enum_type)
        raise ValidationError(f"{name} must be one of: {allowed}") from None


def _query_int(name: str, raw: str | None, default: int) -> int:
    if raw is None:
        return default
    if not raw.isascii() or not raw.isdigit():
        raise ValidationError(f"{name} must be a whole number")
    return int(raw)

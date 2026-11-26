"""Security events as one JSON line each, from a fixed list of fields.

Four things worth an alert are logged as events, not prose: a wrong staff
password, a request refused by a rate limit, a payment webhook whose
signature does not verify, and a donation whose earmarked animal could not be
checked. Each is a JSON object on one line of the service's log, so they can
be searched and counted.

A whitelist, not a scrubber: emit() accepts only the fields in FIELDS, and
only as whole numbers or short codes from this code base. A password, token,
name, email, request body, query string, header or exception message has no
field to go into, so it cannot reach the log by accident. IP addresses are
deliberately absent too (the rate limiter keeps them in memory as keys, and
never logs them).

Pure Python with no web framework, so the donations rules can emit events
too. Identical in every service; tests/test_shared_modules.py fails if the
copies drift (ADR-6: small copies, no shared package).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from enum import StrEnum

LOGGER_NAME = "security_events"


class SecurityEvent(StrEnum):
    STAFF_AUTH_FAILED = "staff_auth_failed"
    RATE_LIMITED = "rate_limited"
    WEBHOOK_SIGNATURE_INVALID = "webhook_signature_invalid"
    EARMARK_NOT_VERIFIED = "earmark_not_verified"


# Every field an event may carry, and what kind of value it takes. Fields
# filled in here (timestamp, level, service, event) or by the request
# context (request_id, route) are listed too, so nothing can overwrite them
# with something else.
INT_FIELDS = frozenset({"status", "donation_id", "animal_id", "suppressed"})
CODE_FIELDS = frozenset({"reason", "policy"})
CONTEXT_FIELDS = frozenset({"request_id", "route"})
FIELDS = frozenset({"timestamp", "level", "service", "event"}) | INT_FIELDS | CODE_FIELDS | CONTEXT_FIELDS

# A code is lower-case letters, digits and underscores, at most 40 long: room
# for "bad_signature" or "public_form", none for a sentence or an email.
_CODE = re.compile(r"[a-z0-9_]{1,40}")
# A route template such as /api/donations/<int:donation_id>, never a filled-in
# path, so no id or query string from a request rides along.
_ROUTE = re.compile(r"[A-Za-z0-9_/<>:.-]{1,120}")
_REQUEST_ID = re.compile(r"[0-9a-f]{32}")


class SecurityEvents:
    """Writes security events. Built once at the composition root (create_app)
    and handed to whatever emits them."""

    def __init__(
        self,
        service: str,
        logger: logging.Logger | None = None,
        context: Callable[[], Mapping[str, str]] = dict,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._service = service
        # Its own logger name, so the events can be told apart from the
        # prose that security.py logs under "security".
        self._logger = logger or logging.getLogger(LOGGER_NAME)
        # Supplies request_id and route while a request is being served; an
        # empty mapping outside one.
        self._context = context
        self._now = now

    def emit(self, event: SecurityEvent, /, **fields: int | str) -> dict[str, int | str]:
        """Log one event and return the record written. Raises ValueError for
        a field outside the whitelist or a value of the wrong kind: that is a
        bug in the caller, and failing loudly is safer than logging it."""
        record: dict[str, int | str] = {
            "timestamp": self._now().isoformat(timespec="seconds"),
            "level": "warning",
            "service": self._service,
            "event": SecurityEvent(event).value,
        }
        for name, value in {**self._context(), **fields}.items():
            record[name] = _checked(name, value)
        self._logger.warning(json.dumps(record, sort_keys=True, ensure_ascii=True))
        return record


def _checked(name: str, value: int | str) -> int | str:
    if name not in FIELDS or name in {"timestamp", "level", "service", "event"}:
        raise ValueError(f"security events have no field {name!r}")
    if name in INT_FIELDS:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{name} must be a whole number")
        return value
    pattern = {"route": _ROUTE, "request_id": _REQUEST_ID}.get(name, _CODE)
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{name} must be a short code, not free text")
    return value

"""Access control for the staff-only endpoints.

One shared password, supplied through the ADMIN_PASSWORD environment variable.
There is no user table and no session.

The organisation has a couple of people who need to admit an animal, move it
through the placement lifecycle and record a donation. Modelling them as user
accounts would mean a users table, password hashing, and a third set of data to
maintain, none of which serves either feature domain. What is actually needed is
a lock on the write endpoints, and one shared secret is the smallest thing that
provides one.
"""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable
from functools import wraps

from flask import current_app, g, jsonify, request

from hardening import STAFF_AUTH, Hardening
from security_events import SecurityEvent

logger = logging.getLogger(__name__)


def require_admin(view: Callable) -> Callable:
    """Reject the request unless it carries the configured admin password.

    The password travels as the password half of an HTTP Basic credential. That
    is not because there are usernames — the username is ignored, there is only
    one principal — but because Basic is a format Flask already parses out of
    the Authorization header, and that both browsers and fetch() know how to
    send. Hand-rolling a custom header would mean parsing it myself for no gain.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        # Every answer from here on, 401 and 429 included, is a staff answer:
        # hardening.py marks it no-store so no cache keeps it.
        g.staff_route = True
        expected = current_app.config["APP_CONFIG"].admin_password

        if not expected:
            # Fail closed. Shipping a default password would be worse than
            # having no admin access at all, because it would look like
            # protection while being public knowledge.
            logger.warning(
                "Refused %s %s: ADMIN_PASSWORD is not set, staff endpoints are disabled",
                request.method,
                request.path,
            )
            return (
                jsonify(
                    error="admin_disabled",
                    detail="Set ADMIN_PASSWORD to enable the staff endpoints.",
                ),
                503,
            )

        # Guessing is limited per client and per service (hardening.py). The
        # limit is checked before the password, so a client that is locked
        # out cannot keep guessing; only wrong passwords count towards it.
        hardening: Hardening = current_app.extensions["hardening"]
        limiter, client = hardening.limiters[STAFF_AUTH], hardening.client()
        decision = limiter.check(client)
        if not decision.allowed:
            return hardening.refuse(STAFF_AUTH, decision)

        credentials = request.authorization
        supplied = credentials.password if credentials else None
        if not supplied:
            # No password at all is not a guess, so it does not count.
            return _unauthorised()
        if not _matches(supplied, expected):
            limiter.record(client)
            hardening.events.emit(SecurityEvent.STAFF_AUTH_FAILED, status=401, reason="wrong_password")
            return _unauthorised()

        return view(*args, **kwargs)

    return wrapper


def _unauthorised():
    logger.warning("Refused %s %s: missing or wrong admin password", request.method, request.path)
    # Deliberately no WWW-Authenticate header. That header makes a browser
    # show its own login box and then remember the password and attach it to
    # every later request to this site by itself, including requests another
    # website triggers: a cross-site request forgery opening. The staff
    # portal adds the password itself, from page memory, so it never needs
    # the browser's help.
    return jsonify(error="unauthorised"), 401


def _matches(supplied: str, expected: str) -> bool:
    """Compare two secrets in constant time.

    `supplied == expected` would return as soon as it hits a differing byte, so
    how long the comparison takes leaks how much of the password was right.
    hmac.compare_digest always examines the whole value. Both sides are encoded
    first because compare_digest rejects str arguments outside ASCII.
    """
    return hmac.compare_digest(supplied.encode("utf-8"), expected.encode("utf-8"))

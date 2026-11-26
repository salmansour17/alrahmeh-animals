"""hardening.py and security_events.py on their own: the rate limiter, the
client's address, the settings and the event whitelist. A fake clock, no
sleeps. Identical in every service, like the modules it tests."""

from __future__ import annotations

import json
import logging
import threading

import pytest

from hardening import (
    PUBLIC_FORM,
    HardeningSettings,
    Policy,
    SlidingWindowLimiter,
    client_address,
)
from security_events import FIELDS, LOGGER_NAME, SecurityEvent, SecurityEvents

FIVE_A_MINUTE = Policy(PUBLIC_FORM, 5, 60)


class Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _limiter(clock: Clock, policy: Policy = FIVE_A_MINUTE, max_keys: int = 100) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(policy, clock, max_keys)


# --- the limiter ---------------------------------------------------------------------


def test_the_limit_is_allowed_then_refused_with_retry_after():
    clock = Clock(0)
    limiter = _limiter(clock)
    assert all(limiter.consume("a").allowed for _ in range(5))
    refused = limiter.consume("a")
    assert not refused.allowed
    # All five in this window: free once this window has become the last one
    # and its weight has dropped below the limit, 60 s from now.
    assert refused.retry_after_s == 60
    clock.now = 10
    assert limiter.consume("a").retry_after_s == 50


def test_the_window_slides_instead_of_resetting_at_once():
    clock = Clock(50)
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.consume("a")
    clock.now = 70  # 10 s into the next window: last window still weighs 5/6
    assert limiter.consume("a").allowed  # estimate 4.17
    refused = limiter.consume("a")  # estimate 5.17
    assert (refused.allowed, refused.retry_after_s) == (False, 2)
    clock.now = 72.01  # the weight has dropped enough
    assert limiter.consume("a").allowed


def test_retry_after_is_never_below_one_second():
    clock = Clock(0)
    limiter = _limiter(clock, Policy(PUBLIC_FORM, 1, 60))
    limiter.consume("a")
    clock.now = 59.5  # half a second of waiting left
    refused = limiter.consume("a")
    assert (refused.allowed, refused.retry_after_s) == (False, 1)


def test_check_counts_nothing_and_record_counts_regardless():
    clock = Clock(0)
    limiter = _limiter(clock)
    for _ in range(10):
        assert limiter.check("a").allowed
    for _ in range(5):
        limiter.record("a")
    assert not limiter.check("a").allowed
    limiter.record("a")  # counted even while over the limit
    clock.now = 125  # two windows later, all forgotten
    assert limiter.check("a").allowed


def test_clients_are_counted_separately():
    limiter = _limiter(Clock(0))
    for _ in range(5):
        limiter.consume("a")
    assert not limiter.consume("a").allowed
    assert limiter.consume("b").allowed


def test_a_flood_is_logged_once_per_window_with_a_count():
    clock = Clock(0)
    limiter = _limiter(clock)
    for _ in range(5):
        limiter.consume("a")
    first = limiter.consume("a")
    assert (first.log_refusal, first.suppressed) == (True, 0)
    assert not any(limiter.consume("a").log_refusal for _ in range(30))
    clock.now = 61  # the next window: refusals were not counted, so one more fits
    assert limiter.consume("a").allowed
    next_first = limiter.consume("a")
    assert (next_first.allowed, next_first.log_refusal, next_first.suppressed) == (False, True, 30)


def test_memory_is_bounded_however_many_clients_appear():
    clock = Clock(0)
    limiter = _limiter(clock, max_keys=50)
    for n in range(1000):
        limiter.consume(f"10.0.{n // 256}.{n % 256}")
    assert len(limiter) == 50


def test_idle_clients_are_dropped_before_active_ones():
    clock = Clock(0)
    limiter = _limiter(clock, max_keys=3)
    limiter.consume("idle")
    clock.now = 200  # "idle" has not been seen for over two windows
    for key in ("a", "b", "c"):
        limiter.consume(key)
    assert len(limiter) == 3
    for _ in range(4):
        limiter.consume("a")
    assert not limiter.consume("a").allowed  # "a" kept its count: "idle" went first


def test_many_threads_at_once_get_exactly_the_limit():
    limiter = _limiter(Clock(0), Policy(PUBLIC_FORM, 25, 60))
    start = threading.Barrier(10)
    allowed: list[bool] = []

    def hammer() -> None:
        start.wait()
        for _ in range(10):
            allowed.append(limiter.consume("same client").allowed)

    threads = [threading.Thread(target=hammer) for _ in range(10)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert allowed.count(True) == 25


# --- the client's address ------------------------------------------------------------


@pytest.mark.parametrize(
    ("remote", "forwarded", "hops", "expected"),
    [
        ("10.0.0.1", None, 1, "10.0.0.1"),  # a direct connection
        ("10.0.0.1", "203.0.113.7", 1, "203.0.113.7"),  # what the ingress saw
        ("10.0.0.1", "1.2.3.4, 203.0.113.7", 1, "203.0.113.7"),  # the left part is the client's invention
        ("10.0.0.1", "1.2.3.4, 198.51.100.2, 203.0.113.7", 2, "198.51.100.2"),
        ("10.0.0.1", "203.0.113.7", 0, "10.0.0.1"),  # no proxy trusted: the header is ignored
        ("10.0.0.1", "203.0.113.7", 2, "10.0.0.1"),  # fewer entries than proxies: not trusted
        ("10.0.0.1", " , 203.0.113.7 ,", 1, "203.0.113.7"),
        (None, None, 1, "unknown"),
    ],
)
def test_the_client_is_read_from_the_right_of_x_forwarded_for(remote, forwarded, hops, expected):
    assert client_address(remote, forwarded, hops) == expected


def test_a_spoofed_header_cannot_dodge_the_limit():
    limiter = _limiter(Clock(0))
    decisions = [limiter.consume(client_address("10.0.0.1", f"192.0.2.{n}, 203.0.113.7", 1)).allowed for n in range(6)]
    assert decisions == [True] * 5 + [False]


# --- settings ------------------------------------------------------------------------------

SETTINGS = [
    "RATE_LIMIT_PUBLIC_FORM_MAX",
    "RATE_LIMIT_PUBLIC_FORM_WINDOW_S",
    "RATE_LIMIT_STAFF_AUTH_MAX",
    "RATE_LIMIT_STAFF_AUTH_WINDOW_S",
    "TRUSTED_PROXY_HOPS",
]


def test_settings_default_without_the_environment(monkeypatch):
    for name in SETTINGS:
        monkeypatch.delenv(name, raising=False)
    assert HardeningSettings.from_environment() == HardeningSettings()


def test_settings_come_from_the_environment(monkeypatch):
    for name, value in zip(SETTINGS, ["10", "30", "3", "600", "0"], strict=True):
        monkeypatch.setenv(name, value)
    settings = HardeningSettings.from_environment()
    assert (settings.public_form.limit, settings.public_form.window_s) == (10, 30)
    assert (settings.staff_auth.limit, settings.staff_auth.window_s) == (3, 600)
    assert settings.trusted_proxy_hops == 0


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("RATE_LIMIT_PUBLIC_FORM_MAX", "0"),
        ("RATE_LIMIT_PUBLIC_FORM_MAX", "-5"),
        ("RATE_LIMIT_PUBLIC_FORM_WINDOW_S", "1.5"),
        ("RATE_LIMIT_STAFF_AUTH_MAX", "lots"),
        ("RATE_LIMIT_STAFF_AUTH_WINDOW_S", "100000"),
        ("TRUSTED_PROXY_HOPS", "6"),
        ("TRUSTED_PROXY_HOPS", "١"),
    ],
)
def test_a_nonsense_setting_stops_the_start(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError, match=name):
        HardeningSettings.from_environment()


# --- security events -------------------------------------------------------------------


def _events(caplog, context=dict) -> SecurityEvents:
    caplog.set_level(logging.WARNING, logger=LOGGER_NAME)
    return SecurityEvents("test", context=context)


def test_an_event_is_one_json_line_of_whitelisted_fields(caplog):
    record = _events(caplog, context=lambda: {"request_id": "ab" * 16, "route": "/api/x/<int:id>"}).emit(
        SecurityEvent.RATE_LIMITED, policy="public_form", status=429, suppressed=3
    )
    (line,) = [r.getMessage() for r in caplog.records if r.name == LOGGER_NAME]
    assert json.loads(line) == record
    assert set(record) <= FIELDS
    assert record["event"] == "rate_limited"
    assert (record["route"], record["status"], record["suppressed"]) == ("/api/x/<int:id>", 429, 3)


@pytest.mark.parametrize(
    "fields",
    [
        {"email": "someone@example.com"},  # not a field at all
        {"ip": "203.0.113.7"},  # addresses are never logged
        {"reason": "Wrong password: CANARY_VALUE"},  # free text, not a code
        {"reason": "x" * 41},
        {"animal_id": "7"},  # a number, not text
        {"status": True},
        {"event": "something_else"},  # fixed by emit itself
        {"service": "other"},
        {"route": "/api/x?token=CANARY_VALUE"},  # a query string is not a template
    ],
)
def test_anything_outside_the_whitelist_is_refused(caplog, fields):
    with pytest.raises(ValueError):
        _events(caplog).emit(SecurityEvent.STAFF_AUTH_FAILED, **fields)
    assert not [r for r in caplog.records if r.name == LOGGER_NAME]


def test_event_names_are_constants():
    assert {e.value for e in SecurityEvent} == {
        "staff_auth_failed",
        "rate_limited",
        "webhook_signature_invalid",
        "earmark_not_verified",
    }

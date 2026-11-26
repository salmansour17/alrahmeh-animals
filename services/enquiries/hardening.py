"""Request hardening shared by the three services (ADR-9): rate limits, the
client's address behind the Container Apps ingress, security headers on every
response, and a request id for the security events.

Identical in every service; tests/test_shared_modules.py fails if the copies
drift. There is no shared package on purpose (ADR-6): one small file per
service keeps the services independent.

Rate limits, in memory. Each container runs one gunicorn process
(entrypoint.sh, WEB_WORKERS=1), so one process sees every request and the
counts are exact. Known limits, accepted: the counts reset whenever the app
scales to zero or restarts, and each service counts on its own, so the
staff-password budget is per service, not for the whole site.

Configuration comes from the environment (system.yaml lists each variable),
read once when the app is built. A nonsense value stops the start with a clear
error instead of running with a limit nobody chose.
"""

from __future__ import annotations

import math
import os
import threading
import time
import uuid
from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from flask import Flask, Response, g, has_request_context, jsonify, request

from security_events import SecurityEvent, SecurityEvents

# --- names -----------------------------------------------------------------------

PUBLIC_FORM = "public_form"
STAFF_AUTH = "staff_auth"

RETRY_AFTER = "Retry-After"
REQUEST_ID = "X-Request-Id"
CACHE_CONTROL = "Cache-Control"

# On every response, error pages included. The APIs answer JSON only, so the
# Content-Security-Policy lets nothing load and nothing frame them. HSTS has
# no preload: that list is hard to leave, and this site's address may change.
SECURITY_HEADERS: Mapping[str, str] = {
    "X-Content-Type-Options": "nosniff",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Referrer-Policy": "no-referrer",
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
}
# Staff answers hold donor and applicant details: no cache may keep them.
STAFF_CACHE_CONTROL = "no-store"


# --- settings ----------------------------------------------------------------------


@dataclass(frozen=True)
class Policy:
    """At most `limit` requests per `window_s` seconds from one client."""

    name: str
    limit: int
    window_s: int


@dataclass(frozen=True)
class HardeningSettings:
    # Five form submissions a minute is plenty for a person, little for a bot.
    public_form: Policy = Policy(PUBLIC_FORM, 5, 60)
    # Five wrong staff passwords in fifteen minutes, then wait.
    staff_auth: Policy = Policy(STAFF_AUTH, 5, 900)
    # How many proxies in front of the app add to X-Forwarded-For: one, the
    # Container Apps ingress. 0 trusts no header at all (direct connections).
    trusted_proxy_hops: int = 1
    # The most clients tracked at once per limit, so a flood of addresses
    # cannot exhaust memory.
    max_tracked_clients: int = 10_000

    @classmethod
    def from_environment(cls) -> HardeningSettings:
        return cls(
            public_form=Policy(
                PUBLIC_FORM,
                _env_int("RATE_LIMIT_PUBLIC_FORM_MAX", 5, 1, 1000),
                _env_int("RATE_LIMIT_PUBLIC_FORM_WINDOW_S", 60, 1, 86400),
            ),
            staff_auth=Policy(
                STAFF_AUTH,
                _env_int("RATE_LIMIT_STAFF_AUTH_MAX", 5, 1, 1000),
                _env_int("RATE_LIMIT_STAFF_AUTH_WINDOW_S", 900, 1, 86400),
            ),
            trusted_proxy_hops=_env_int("TRUSTED_PROXY_HOPS", 1, 0, 5),
        )


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    """A whole number in [minimum, maximum]; unset means the default. Anything
    else raises ValueError, which stops the start (fail fast)."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    if not raw.isascii() or not raw.isdigit() or not minimum <= int(raw) <= maximum:
        raise ValueError(f"{name} must be a whole number from {minimum} to {maximum}")
    return int(raw)


# --- the limiter ----------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """The answer for one request. retry_after_s is whole seconds, at least 1,
    when refused. log_refusal is True only for the first refusal of a client
    in a window, so a flood writes one log line, not thousands; suppressed is
    how many refusals went unlogged since the last line."""

    allowed: bool
    retry_after_s: int = 0
    log_refusal: bool = False
    suppressed: int = 0


@dataclass
class _Counts:
    window_start: float
    current: int = 0
    previous: int = 0
    last_seen: float = 0.0
    logged_window: float | None = None
    unlogged: int = 0


class SlidingWindowLimiter:
    """The sliding window counter: for each client, a count for this fixed
    window and the last one, with the last weighted by how much of it still
    overlaps the sliding window. Smooth like a true sliding log, but two
    numbers per client instead of a timestamp per request.

    Thread safe (one lock), with an injected clock so tests never sleep, and
    bounded: idle clients are dropped first, then the least recently seen.
    """

    def __init__(self, policy: Policy, clock: Callable[[], float] = time.monotonic, max_keys: int = 10_000) -> None:
        self.policy = policy
        self._clock = clock
        self._max_keys = max_keys
        self._lock = threading.Lock()
        self._counts: OrderedDict[str, _Counts] = OrderedDict()

    def check(self, key: str) -> Decision:
        """Would one more be allowed? Counts nothing."""
        with self._lock:
            return self._decide(key, count=False)

    def record(self, key: str) -> None:
        """Count one, whatever the limit says (a wrong password is counted
        even when it arrives over the limit)."""
        with self._lock:
            now = self._clock()
            self._counts_for(key, now).current += 1

    def consume(self, key: str) -> Decision:
        """Count one if allowed, and say whether it was."""
        with self._lock:
            return self._decide(key, count=True)

    def __len__(self) -> int:
        with self._lock:
            return len(self._counts)

    def _decide(self, key: str, count: bool) -> Decision:
        now = self._clock()
        counts = self._counts_for(key, now)
        window = self.policy.window_s
        weight = 1 - (now - counts.window_start) / window
        if counts.previous * weight + counts.current < self.policy.limit:
            if count:
                counts.current += 1
            return Decision(allowed=True)
        retry_after_s = max(1, math.ceil(self._wait(counts, now)))
        if counts.logged_window != counts.window_start:
            counts.logged_window, suppressed, counts.unlogged = counts.window_start, counts.unlogged, 0
            return Decision(False, retry_after_s, log_refusal=True, suppressed=suppressed)
        counts.unlogged += 1
        return Decision(False, retry_after_s)

    def _wait(self, counts: _Counts, now: float) -> float:
        """Seconds until the estimate drops below the limit, if nothing more
        arrives: within this window if the last one's weight is what holds it
        up, otherwise once this window has become the last one."""
        window, limit = self.policy.window_s, self.policy.limit
        if counts.current < limit:
            free_at = counts.window_start + window * (1 - (limit - counts.current) / counts.previous)
        else:
            free_at = counts.window_start + window + window * (1 - limit / counts.current)
        return free_at - now

    def _counts_for(self, key: str, now: float) -> _Counts:
        window = self.policy.window_s
        start = math.floor(now / window) * window
        counts = self._counts.get(key)
        if counts is None:
            self._make_room(now)
            counts = self._counts[key] = _Counts(window_start=start)
        elif counts.window_start != start:
            counts.previous = counts.current if counts.window_start == start - window else 0
            counts.current, counts.window_start = 0, start
        counts.last_seen = now
        self._counts.move_to_end(key)
        return counts

    def _make_room(self, now: float) -> None:
        idle_before = now - 2 * self.policy.window_s
        while self._counts and next(iter(self._counts.values())).last_seen < idle_before:
            self._counts.popitem(last=False)
        while len(self._counts) >= self._max_keys:
            self._counts.popitem(last=False)


# --- the client's address ------------------------------------------------------------


def client_address(remote_addr: str | None, forwarded_for: str | None, trusted_hops: int) -> str:
    """The address to count a request against.

    Behind the ingress, the connection comes from the proxy, which appends the
    address it saw to X-Forwarded-For. Anything to the left of that came from
    the client and could be invented, so the leftmost value is never trusted:
    with N trusted proxies, the client is the Nth address from the right.
    Without the header (a direct connection), or with fewer entries than
    trusted proxies, the connection's own address is used.
    """
    if trusted_hops > 0 and forwarded_for:
        hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
        if len(hops) >= trusted_hops:
            return hops[-trusted_hops]
    return remote_addr or "unknown"


# --- wiring into Flask --------------------------------------------------------------


@dataclass
class Hardening:
    """Everything above, built once in create_app and kept on the app."""

    settings: HardeningSettings
    events: SecurityEvents
    clock: Callable[[], float] = time.monotonic
    limiters: dict[str, SlidingWindowLimiter] = field(init=False)

    def __post_init__(self) -> None:
        self.limiters = {
            policy.name: SlidingWindowLimiter(policy, self.clock, self.settings.max_tracked_clients)
            for policy in (self.settings.public_form, self.settings.staff_auth)
        }

    def client(self) -> str:
        return client_address(
            request.remote_addr, request.headers.get("X-Forwarded-For"), self.settings.trusted_proxy_hops
        )

    def refuse(self, policy: str, decision: Decision) -> Response:
        """429 in the project's error shape, with Retry-After, and an event
        for the first refusal of a client in a window."""
        if decision.log_refusal:
            self.events.emit(SecurityEvent.RATE_LIMITED, policy=policy, status=429, suppressed=decision.suppressed)
        response = jsonify(
            error="rate_limited",
            detail=f"Too many requests. Please try again in {decision.retry_after_s} seconds.",
        )
        response.status_code = 429
        response.headers[RETRY_AFTER] = str(decision.retry_after_s)
        return response


def request_context() -> dict[str, str]:
    """The request id and route template, for security events; empty outside
    a request."""
    if not has_request_context():
        return {}
    context = {}
    if "request_id" in g:
        context["request_id"] = g.request_id
    if request.url_rule is not None:
        context["route"] = request.url_rule.rule
    return context


def install_hardening(app: Flask, hardening: Hardening, limited: Mapping[str, str]) -> None:
    """Rate-limit the endpoints named in `limited` (endpoint -> policy), and
    add the security headers to every response.

    Declarative: which endpoint has which limit is one dictionary in
    create_app, not checks inside handlers. Health, the webhook and
    everything not listed are never limited here; staff authentication has
    its own limit, in security.py.
    """
    app.extensions["hardening"] = hardening

    @app.before_request
    def _limit():
        g.request_id = uuid.uuid4().hex
        policy = limited.get(request.endpoint or "")
        # A CORS preflight is the browser asking permission, not a submission.
        if policy is None or request.method == "OPTIONS":
            return None
        decision = hardening.limiters[policy].consume(hardening.client())
        return None if decision.allowed else hardening.refuse(policy, decision)

    @app.after_request
    def _headers(response: Response) -> Response:
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        if "request_id" in g:
            response.headers[REQUEST_ID] = g.request_id
        if g.get("staff_route"):
            response.headers[CACHE_CONTROL] = STAFF_CACHE_CONTROL
        return response

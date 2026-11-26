"""The donations service's only line to another service (ADR-6).

Two adapters, two separate questions to the animals service:

- HttpAnimalDirectory implements the AnimalDirectory interface that
  service.py declares: "does animal N exist?", for the earmark check. It is
  never cached: a stale answer could put money against the wrong animal.
- HttpAnimalNames implements AnimalNames: "what are these animals called?",
  for the staff donation list, many ids in one request. Only this one is
  wrapped in a cache (name_cache.py, built in create_app). Being separate
  classes, the earmark check has no way to reach the cache.

Each is an Adapter: the donation rules call plain methods, and only this file
knows a network is involved.

It uses the standard library's urllib rather than a package such as requests,
because one GET with a deadline needs nothing more.

Why a deadline and a worker thread, not just urlopen(timeout=...): urllib's
timeout applies to each socket operation (connecting, reading), but not to
looking up the host name first, which can block for seconds on its own. With
the animals container stopped, Docker's DNS took about two seconds to say the
name no longer existed, and a two-second timeout became a 3.9-second wait. So
each call computes one deadline when it starts, runs the whole request, name
lookup included, in a worker thread, and waits for it only until the deadline.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from donations.service import AnimalsUnavailable

logger = logging.getLogger(__name__)

# A few threads per process for calls to the animals service. A call that hits
# its deadline is abandoned, not killed: its thread finishes on its own (the
# socket timeout still bounds it once connected), so the pool only needs to
# absorb the occasional slow name lookup.
_WORKERS = ThreadPoolExecutor(max_workers=4, thread_name_prefix="animals-client")

# The endpoints this service calls on the animals service, and what each of
# their answers means here. contracts/check_contracts.py compares these with
# the animals service's openapi.yaml, so neither side can change without the
# other.
ANIMAL_METHOD = "GET"
ANIMAL_PATH = "/api/animals/{animal_id}"
ANSWERS = {200: True, 404: False}
NAMES_METHOD = "GET"
NAMES_PATH = "/api/animals/names"
# 400 means this service sent ids the animals service refuses: a bug here,
# treated like any other failure to answer (the list shows ids, not names).
NAMES_ANSWERS = {200: "names", 400: "refused"}

# An answer larger than this is not a list of names; reading it would only
# waste memory.
MAX_ANSWER_BYTES = 256 * 1024


class HttpAnimalDirectory:
    """Answers "does this animal exist?" with GET /api/animals/<id> on the
    animals service.

    200 means yes and 404 means no: both are definite answers. Anything else
    (no answer by the deadline, a refused connection, an unknown host, a 5xx)
    means the animals service could not answer, and raises AnimalsUnavailable
    so each caller can apply its own rule for that case instead of guessing
    here.
    """

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        # The whole call, from name lookup to the last byte, gets at most this
        # long, so a stopped or slow animals service can never hang a request.
        self._timeout_s = timeout_s

    def exists(self, animal_id: int) -> bool:
        deadline = time.monotonic() + self._timeout_s
        url = self._base_url + ANIMAL_PATH.format(animal_id=int(animal_id))
        try:
            status, _ = _get(url, deadline)
        except AnimalsUnavailable as error:
            logger.warning("Animals service unavailable while checking animal %d: %s", animal_id, error)
            raise
        if status in ANSWERS:
            return ANSWERS[status]
        logger.warning("Animals service answered %d for animal %d", status, animal_id)
        raise AnimalsUnavailable(f"animals service answered {status}")


class HttpAnimalNames:
    """Answers "what are these animals called?" with one GET
    /api/animals/names?ids=... on the animals service, for a whole page of
    the staff donation list.

    Returns {id: name}; an id the animals service does not know is simply
    absent. Anything but a well-formed 200 (no answer by the deadline, a 400
    or 5xx, a body that is not the documented shape) raises
    AnimalsUnavailable, and the caller shows ids instead of names.
    """

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s

    def names(self, animal_ids: Iterable[int]) -> dict[int, str]:
        ids = sorted({int(animal_id) for animal_id in animal_ids})
        if not ids:
            return {}
        deadline = time.monotonic() + self._timeout_s
        url = f"{self._base_url}{NAMES_PATH}?ids={','.join(map(str, ids))}"
        try:
            status, body = _get(url, deadline)
            if NAMES_ANSWERS.get(status) != "names":
                raise AnimalsUnavailable(f"animals service answered {status}")
            return _parse_names(body)
        except AnimalsUnavailable as error:
            logger.warning("Animal names unavailable for %d animals: %s", len(ids), error)
            raise


def _parse_names(body: bytes) -> dict[int, str]:
    """{"animals": [{"id": 1, "name": "Luna"}, ...]} -> {1: "Luna"}. Anything
    else is not trusted: a malformed answer is the same as no answer."""
    try:
        document = json.loads(body)
        names = {}
        for animal in document["animals"]:
            animal_id, name = animal["id"], animal["name"]
            if isinstance(animal_id, bool) or not isinstance(animal_id, int) or not isinstance(name, str):
                raise TypeError("an id or a name of the wrong type")
            names[animal_id] = name
    except (ValueError, TypeError, KeyError) as error:
        raise AnimalsUnavailable(f"malformed answer from the animals service ({type(error).__name__})") from None
    return names


def _get(url: str, deadline: float) -> tuple[int, bytes]:
    """GET `url` and return its status code and body, or raise
    AnimalsUnavailable if there is no answer by `deadline` (a
    time.monotonic() value)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AnimalsUnavailable("no time left before the deadline")
    future = _WORKERS.submit(_fetch, url, remaining)
    try:
        # Recomputed here, so the time spent queueing for a worker counts too.
        return future.result(timeout=max(deadline - time.monotonic(), 0))
    except FutureTimeout:
        raise AnimalsUnavailable("no answer before the deadline") from None


def _fetch(url: str, socket_timeout_s: float) -> tuple[int, bytes]:
    """Runs in a worker thread: the request itself."""
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=socket_timeout_s) as response:
            return response.status, response.read(MAX_ANSWER_BYTES)
    except HTTPError as error:
        # urlopen raises for every 4xx and 5xx. The status is the answer; the
        # caller decides what it means.
        return error.code, b""
    except (URLError, TimeoutError, OSError) as error:
        # URLError: refused connection or unknown host. TimeoutError: a socket
        # operation took too long. OSError: anything else at socket level.
        raise AnimalsUnavailable(f"animals service unreachable ({type(error).__name__})") from error

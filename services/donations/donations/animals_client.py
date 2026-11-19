"""The donations service's only line to another service (ADR-6).

HttpAnimalDirectory implements the AnimalDirectory interface that service.py
declares, by asking the animals service over HTTP. It is an Adapter: the
donation rules keep calling exists() exactly as they did when the answer came
from an in-process object, and only this file knows a network is involved.

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

import logging
import time
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
        url = f"{self._base_url}/api/animals/{int(animal_id)}"
        try:
            status = _get_status(url, deadline)
        except AnimalsUnavailable as error:
            logger.warning("Animals service unavailable while checking animal %d: %s", animal_id, error)
            raise
        if status == 200:
            return True
        if status == 404:
            return False
        logger.warning("Animals service answered %d for animal %d", status, animal_id)
        raise AnimalsUnavailable(f"animals service answered {status}")


def _get_status(url: str, deadline: float) -> int:
    """GET `url` and return its status code, or raise AnimalsUnavailable if
    there is no answer by `deadline` (a time.monotonic() value)."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise AnimalsUnavailable("no time left before the deadline")
    future = _WORKERS.submit(_fetch_status, url, remaining)
    try:
        # Recomputed here, so the time spent queueing for a worker counts too.
        return future.result(timeout=max(deadline - time.monotonic(), 0))
    except FutureTimeout:
        raise AnimalsUnavailable("no answer before the deadline") from None


def _fetch_status(url: str, socket_timeout_s: float) -> int:
    """Runs in a worker thread: the request itself."""
    request = Request(url, headers={"Accept": "application/json"})
    try:
        with urlopen(request, timeout=socket_timeout_s) as response:
            return response.status
    except HTTPError as error:
        # urlopen raises for every 4xx and 5xx. The status is the answer; the
        # caller decides what it means.
        return error.code
    except (URLError, TimeoutError, OSError) as error:
        # URLError: refused connection or unknown host. TimeoutError: a socket
        # operation took too long. OSError: anything else at socket level.
        raise AnimalsUnavailable(f"animals service unreachable ({type(error).__name__})") from error

"""The donations service's only line to another service (ADR-6).

HttpAnimalDirectory implements the AnimalDirectory interface that service.py
declares, by asking the animals service over HTTP. It is an Adapter: the
donation rules keep calling exists() exactly as they did when the answer came
from an in-process object, and only this file knows a network is involved.

It uses the standard library's urllib rather than a package such as requests,
because one GET with a timeout needs nothing more.
"""

from __future__ import annotations

import logging
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from donations.service import AnimalsUnavailable

logger = logging.getLogger(__name__)


class HttpAnimalDirectory:
    """Answers "does this animal exist?" with GET /api/animals/<id> on the
    animals service.

    200 means yes and 404 means no: both are definite answers. Anything else
    (a timeout, a refused connection, a 5xx) means the animals service could
    not answer, and raises AnimalsUnavailable so each caller can apply its own
    rule for that case instead of guessing here.
    """

    def __init__(self, base_url: str, timeout_s: float) -> None:
        self._base_url = base_url.rstrip("/")
        # Every call carries this timeout, so a stopped or slow animals service
        # costs a request here at most this long, never a hung worker.
        self._timeout_s = timeout_s

    def exists(self, animal_id: int) -> bool:
        url = f"{self._base_url}/api/animals/{int(animal_id)}"
        request = Request(url, headers={"Accept": "application/json"})
        try:
            with urlopen(request, timeout=self._timeout_s) as response:
                return response.status == 200
        except HTTPError as error:
            # urlopen raises for every 4xx/5xx; a 404 is a real answer.
            if error.code == 404:
                return False
            logger.warning("Animals service answered %d for animal %d", error.code, animal_id)
            raise AnimalsUnavailable(f"animals service answered {error.code}") from error
        except (URLError, TimeoutError, OSError) as error:
            # URLError: refused connection or unknown host. TimeoutError: no
            # answer within the timeout. OSError: anything else at socket level.
            logger.warning("Animals service unreachable while checking animal %d: %s", animal_id, error)
            raise AnimalsUnavailable("animals service unreachable") from error

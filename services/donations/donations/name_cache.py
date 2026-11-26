"""The app-level cache in front of the animals service's names (backend slides:
"application-level cache"; ADR-6).

CachedAnimalNames is a Proxy: it has the same names() method as the
HttpAnimalNames it wraps, so DonationService cannot tell them apart, and
create_app decides whether a cache sits in between. A page of the staff list
asks for, say, three animals' names; the first load fetches them in one
request, and every load in the next few minutes is answered from memory.

Rules:
- Only the ids not already fresh in the cache are fetched, in one request.
- A failure is never cached: the next load asks again.
- An id the animals service does not know is not cached either; it is rare,
  and caching it would hide an animal admitted a moment later.
- Entries live ttl_s seconds; at most max_entries are kept, the oldest
  dropped first, so the cache cannot grow without bound.
- One lock guards the dictionary, because the server answers on several
  threads. The network call happens outside it, so a slow animals service
  never makes other requests wait for the lock.

It is for display only. The earmark check never uses it (animals_client.py).
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Iterable

from donations.service import AnimalNames


class CachedAnimalNames:
    def __init__(
        self,
        source: AnimalNames,
        ttl_s: float,
        max_entries: int,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if ttl_s <= 0 or max_entries < 1:
            raise ValueError("the name cache needs a positive time to live and room for at least one entry")
        self._source = source
        self._ttl_s = ttl_s
        self._max_entries = max_entries
        self._clock = clock
        self._lock = threading.Lock()
        # id -> (name, expires_at); insertion order is age order.
        self._entries: OrderedDict[int, tuple[str, float]] = OrderedDict()

    def names(self, animal_ids: Iterable[int]) -> dict[int, str]:
        wanted = set(animal_ids)
        found: dict[int, str] = {}
        now = self._clock()
        with self._lock:
            for animal_id in wanted:
                entry = self._entries.get(animal_id)
                if entry is not None and entry[1] > now:
                    found[animal_id] = entry[0]
        missing = wanted - found.keys()
        if missing:
            # May raise AnimalsUnavailable: nothing is stored, and the caller
            # shows ids for this page.
            fetched = self._source.names(missing)
            self._store(fetched, now + self._ttl_s)
            found.update(fetched)
        return found

    def _store(self, fetched: dict[int, str], expires_at: float) -> None:
        with self._lock:
            for animal_id, name in fetched.items():
                self._entries.pop(animal_id, None)  # re-inserted as the newest
                self._entries[animal_id] = (name, expires_at)
            now = self._clock()
            for animal_id in [i for i, (_, expiry) in self._entries.items() if expiry <= now]:
                del self._entries[animal_id]
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

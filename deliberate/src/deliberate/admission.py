"""Per-replica admission control onto the shared backend.

Phase 0 is deliberately the simple half of the design in
``docs/deliberate/04-parallelism-and-pidev.md`` §3: a bounded number of concurrent
in-flight backend calls per replica, with callers *queueing* (up to a max wait)
rather than failing when at capacity. Fair-queueing, priority classes and a shared
cross-replica broker are Phase 4 — the doc says to start with per-replica caps and
only build the broker if measurement shows unfairness.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager


class AdmissionFull(Exception):
    """Raised when a caller waits longer than ``max_wait_s`` for a slot."""


class Admission:
    def __init__(self, max_concurrent: int, max_wait_s: float) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)
        self._max_wait_s = max_wait_s
        self.max_concurrent = max_concurrent

    @asynccontextmanager
    async def slot(self):
        try:
            await asyncio.wait_for(self._sem.acquire(), timeout=self._max_wait_s)
        except asyncio.TimeoutError as exc:
            raise AdmissionFull(
                f"no capacity within {self._max_wait_s}s "
                f"(max_concurrent={self.max_concurrent})"
            ) from exc
        try:
            yield
        finally:
            self._sem.release()

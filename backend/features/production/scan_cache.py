# features/production/scan_cache.py — short-lived, single-flight cache of GET /production.
#
# The production read (production.json + publish events + full disk scan) is the
# heaviest request FLUX makes against the share. When many windows refresh at once
# the scans stacked up in the backend (5-19 s measured, 2026-10-22). This cache:
#   * shares one computation between concurrent callers of the same project
#     (single-flight);
#   * reuses the result for TTL_S seconds (changes made on other machines show up
#     within that delay);
#   * drops everything as soon as this backend writes something (invalidate_all,
#     called by the main.py middleware after any mutating request), so a local
#     create / publish / rename is visible on the very next read.

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Awaitable, Callable

TTL_S = 1.0

_generation = 0
# project -> (generation, monotonic time, result, etag)
_results: dict[str, tuple[int, float, dict, str]] = {}
# project -> (generation, task) of the computation in flight
_inflight: dict[str, tuple[int, asyncio.Task]] = {}


def invalidate_all() -> None:
    """Forget every cached result; computations in flight are not reused either."""
    global _generation
    _generation += 1
    _results.clear()


def _etag_for(result: dict) -> str:
    raw = json.dumps(result, sort_keys=True, default=str, separators=(",", ":"))
    return f'W/"{hashlib.sha1(raw.encode()).hexdigest()[:16]}"'


async def get(project: str, compute: Callable[[], Awaitable[dict]]) -> tuple[dict, str]:
    """Return (result, etag) for *project*, computing it at most once at a time."""
    key = project.lower()
    gen = _generation
    hit = _results.get(key)
    if hit is not None and hit[0] == gen and time.monotonic() - hit[1] < TTL_S:
        return hit[2], hit[3]

    running = _inflight.get(key)
    if running is None or running[0] != gen:
        async def _run() -> tuple[dict, str]:
            try:
                result = await compute()
                etag = _etag_for(result)
                if _generation == gen:                  # not invalidated meanwhile
                    _results[key] = (gen, time.monotonic(), result, etag)
                return result, etag
            finally:
                cur = _inflight.get(key)
                if cur is not None and cur[0] == gen:
                    _inflight.pop(key, None)

        running = (gen, asyncio.ensure_future(_run()))
        _inflight[key] = running
    # shield: a client that disconnects must not cancel the shared computation.
    return await asyncio.shield(running[1])


def _reset_for_tests() -> None:
    global _generation
    _generation = 0
    _results.clear()
    _inflight.clear()


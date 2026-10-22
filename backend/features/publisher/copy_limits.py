# features/publisher/copy_limits.py — caps on the source -> vNNN publish copy.
#
# Measured 2026-10-22 on the school share: heavy publishes started together are the
# only load that saturates the server. Two per-machine settings (Parametres avances):
#   * FLUX_PUBLISH_MAX_PARALLEL : publish copies running at once in this backend
#     (default 10); the next ones wait their turn.
#   * FLUX_PUBLISH_MAX_MBPS     : throughput cap per copy in MB/s (0 = off, default).
#     Off keeps shutil.copy2 (fastest path, server-side copy when both ends are on
#     the share); on switches to a chunked copy that sleeps to stay under the cap.
# Only the network-heavy copy goes through here; LAST is derived from vNNN on the
# share (last_pointer.write_last) and stays a plain copy2. No cross-machine
# coordination (no lock file on the share).

from __future__ import annotations

import os
import shutil
import threading
import time
from contextlib import contextmanager
from pathlib import Path

DEFAULT_MAX_PARALLEL = 10
_CHUNK = 4 * 1024 * 1024

_cond = threading.Condition()
_active = 0
_waiting = 0


def max_parallel() -> int:
    try:
        value = int(float(os.environ.get("FLUX_PUBLISH_MAX_PARALLEL", DEFAULT_MAX_PARALLEL)))
    except ValueError:
        value = DEFAULT_MAX_PARALLEL
    return max(1, value)


def max_mbps() -> float:
    try:
        value = float(os.environ.get("FLUX_PUBLISH_MAX_MBPS", "0"))
    except ValueError:
        value = 0.0
    return max(0.0, value)


def status() -> dict:
    """Copies running / waiting in this backend (for the UI)."""
    with _cond:
        return {"active": _active, "waiting": _waiting, "max_parallel": max_parallel(),
                "max_mbps": max_mbps()}


@contextmanager
def slot():
    """Hold one of the max_parallel() copy slots (re-read each time, so a new value
    from the settings page applies to the next copies without a restart)."""
    global _active, _waiting
    with _cond:
        _waiting += 1
        try:
            while _active >= max_parallel():
                _cond.wait()
        finally:
            _waiting -= 1
        _active += 1
    try:
        yield
    finally:
        with _cond:
            _active -= 1
            _cond.notify_all()


def _throttled_copy(src: str, dst: str, mbps: float) -> str:
    rate = mbps * 1024 * 1024
    start = time.monotonic()
    done = 0
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        while True:
            buf = fin.read(_CHUNK)
            if not buf:
                break
            fout.write(buf)
            done += len(buf)
            ahead = done / rate - (time.monotonic() - start)
            if ahead > 0:
                time.sleep(ahead)
    shutil.copystat(src, dst)
    return dst


def _copy_function():
    mbps = max_mbps()
    if mbps <= 0:
        return shutil.copy2
    return lambda s, d: _throttled_copy(str(s), str(d), mbps)


def copy_file(source: Path, target: Path) -> None:
    with slot():
        _copy_function()(source, target)


def copy_tree(source: Path, target: Path) -> None:
    with slot():
        shutil.copytree(source, target, copy_function=_copy_function())

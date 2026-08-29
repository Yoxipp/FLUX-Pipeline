# stage_factory.py — isolated creation of Usd.Stage objects (the only entry
# point for stages, so tests can spin one up without touching disk).

from __future__ import annotations

import os
from pathlib import Path

from pxr import Usd

# Test-only stage keepalive. On Windows/usd-core, destroying an anonymous
# Usd.Stage mid-process can abort a USD worker thread (STATUS_BREAKPOINT). The
# test harness (tests/run_tests.py) sets this env var and hard-exits via
# ``os._exit`` without teardown, so holding every stage alive for the run's
# duration sidesteps the crash without leaking in production (var unset there).
_KEEPALIVE_ENV = "USD_ASM_KEEPALIVE_STAGES"
_KEEPALIVE: list = []


def _track(stage: "Usd.Stage") -> "Usd.Stage":
    """Pin *stage* alive for the process when running under the test harness."""
    if os.environ.get(_KEEPALIVE_ENV) == "1":
        _KEEPALIVE.append(stage)
    return stage


def in_memory() -> "Usd.Stage":
    """Return a fresh anonymous in-memory stage (no disk I/O).

    Payloads are left unloaded (``LoadNone``): the assembler only *authors*
    composition arcs, it never needs the referenced geometry resolved. This also
    avoids USD attempting to open not-yet-published assets during composition,
    which on Windows/usd-core can abort a worker thread on teardown.
    """
    return _track(Usd.Stage.CreateInMemory(load=Usd.Stage.LoadNone))


def new_stage(root_path: str | Path) -> "Usd.Stage":
    """Create a new stage whose root layer is *root_path*.

    The file extension (.usda/.usdc/.usd) selects the on-disk format. Parent
    directories are created if missing.
    """
    path = Path(root_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return _track(Usd.Stage.CreateNew(str(path)))

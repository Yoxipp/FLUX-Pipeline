# hosts.py — which workstation runs the shared active flows (01_ARCHITECTURE §9, 00_LOGIQUE n°2).
#
# The election itself is core/host_lock.py (shared with the Discord bot, ADR 0082); this module
# names the lock of the Flows: CONFIG/extensions/runs/host.lock.

from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.host_lock import (  # noqa: F401 - re-exported for the scheduler and the tests
    BEAT_S, CONFIRM_S, MAX_READ_FAILURES, SETTLE_S, TTL_S, HostLock,
)

LOCK_NAME = "host.lock"


def lock_path() -> Optional[Path]:
    """CONFIG/extensions/runs/host.lock, None without FLUX_ROOT."""
    from flux_flows import locations

    try:
        return locations.extensions_dir() / "runs" / LOCK_NAME
    except RuntimeError:
        return None

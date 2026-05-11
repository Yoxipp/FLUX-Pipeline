# launcher_core.py — detect installed DCCs and launch them as detached processes.

from __future__ import annotations

import glob
import subprocess
from pathlib import Path

from core import config
from core.constants import DCC_EXE_PATTERNS
from core.logger import get_logger

log = get_logger(__name__)

# Windows DETACHED_PROCESS flag — process keeps running after hub closes
_DETACHED_PROCESS = 0x00000008


# ── public API ────────────────────────────────────────────────────────────────

def get_installed_dccs() -> dict[str, str]:
    """Return {dcc_name: exe_path} for all DCCs detected on this machine.

    Checks user-configured custom paths first, then glob-scans default install dirs.
    """
    found: dict[str, str] = {}
    for dcc_name, patterns in DCC_EXE_PATTERNS.items():
        custom = config.get_dcc_exe(dcc_name)
        if custom and Path(custom).is_file():
            found[dcc_name] = custom
            continue
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                # sort to pick the highest version number when multiple are installed
                found[dcc_name] = sorted(matches)[-1]
                break
    return found


def launch_dcc(dcc_name: str) -> bool:
    """Launch *dcc_name* as a detached process. Returns True if the process started."""
    exe = _resolve_exe(dcc_name)
    if exe is None:
        log.warning("No executable found for '%s'", dcc_name)
        return False
    try:
        subprocess.Popen(
            [exe],
            creationflags=_DETACHED_PROCESS,
            close_fds=True,
        )
        log.info("Launched %s — %s", dcc_name, exe)
        return True
    except OSError as e:
        log.error("Failed to launch %s: %s", dcc_name, e)
        return False


def get_custom_exe_path(dcc_name: str) -> str | None:
    """Return user-configured exe path for *dcc_name*, or None."""
    return config.get_dcc_exe(dcc_name)


def set_custom_exe_path(dcc_name: str, path: str) -> None:
    """Persist a custom exe path for *dcc_name* in user settings."""
    config.set_dcc_exe(dcc_name, path)
    log.info("Custom exe set for %s: %s", dcc_name, path)


# ── private ───────────────────────────────────────────────────────────────────

def _resolve_exe(dcc_name: str) -> str | None:
    """Return exe path: custom setting first, then auto-detected, then None."""
    custom = config.get_dcc_exe(dcc_name)
    if custom and Path(custom).is_file():
        return custom
    return get_installed_dccs().get(dcc_name)


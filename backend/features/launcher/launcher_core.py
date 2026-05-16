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

# Map frontend lowercase keys → DCC_EXE_PATTERNS keys
_FRONTEND_KEY_MAP: dict[str, str] = {
    "maya":               "Maya",
    "houdini":            "Houdini",
    "nuke":               "Nuke",
    "substance_painter":  "SubstanceP",
    "substance_designer": "SubstanceD",
    "zbrush":             "ZBrush",
    "marvelous":          "Marvelous",
    "photoshop":          "Photoshop",
}


# ── public API ────────────────────────────────────────────────────────────────

def get_installed_dccs() -> dict[str, str]:
    """Return {frontend_key: exe_path} — keys are lowercase (e.g. 'houdini', 'maya').

    Checks user-configured custom paths first, then glob-scans default install dirs.
    """
    found: dict[str, str] = {}
    for frontend_key, internal_key in _FRONTEND_KEY_MAP.items():
        patterns = DCC_EXE_PATTERNS.get(internal_key, [])
        custom = config.get_dcc_exe(frontend_key)
        if custom and Path(custom).is_file():
            found[frontend_key] = custom
            continue
        for pattern in patterns:
            matches = glob.glob(pattern)
            if matches:
                found[frontend_key] = sorted(matches)[-1]
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


def find_dcc_exe(dcc_key: str) -> str | None:
    """Glob-scan default install dirs for *dcc_key*, save to config if found.

    *dcc_key* is the frontend lowercase key (e.g. 'maya', 'substance_painter').
    Returns the found path, or None if nothing matches.
    """
    internal = _FRONTEND_KEY_MAP.get(dcc_key)
    if not internal:
        log.warning("find_dcc_exe: unknown key '%s'", dcc_key)
        return None
    patterns = DCC_EXE_PATTERNS.get(internal, [])
    for pattern in patterns:
        matches = glob.glob(pattern)
        if matches:
            path = sorted(matches)[-1]
            config.set_dcc_exe(dcc_key, path)
            log.info("Auto-found %s → %s", dcc_key, path)
            return path
    log.info("Auto-find: no exe found for '%s'", dcc_key)
    return None


# ── private ───────────────────────────────────────────────────────────────────

def _resolve_exe(dcc_name: str) -> str | None:
    """Return exe path: custom setting first, then auto-detected, then None."""
    custom = config.get_dcc_exe(dcc_name)
    if custom and Path(custom).is_file():
        return custom
    return get_installed_dccs().get(dcc_name)


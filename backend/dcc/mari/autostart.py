# autostart.py — install the FLUX bridge into Mari's scripts dir (V6 B7).
#
# Same shape as the other DCC autostart modules. Mari runs Python from its scripts
# path; we drop the bridge there. NOTE: Mari does not auto-run arbitrary scripts the
# way Nuke runs init.py — the user may need MARI_SCRIPT_PATH to include this dir and
# a startup that calls flux_mari_bridge.start(). Verify live.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "mari_bridge.py"
_PLUGIN_NAME = "flux_mari_bridge.py"


def _scripts_dir() -> Path:
    """Best-effort Mari user scripts dir (override via FLUX_MARI_SCRIPTS_DIR)."""
    override = os.environ.get("FLUX_MARI_SCRIPTS_DIR")
    if override:
        return Path(override)
    return Path.home() / "Mari" / "Scripts"


def get_startup_file(exe_path: str | None = None) -> Path | None:
    return _scripts_dir() / _PLUGIN_NAME


def is_installed(exe_path: str | None = None) -> bool:
    f = get_startup_file()
    return bool(f and f.exists())


def install(exe_path: str | None = None) -> dict:
    dest = get_startup_file()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_PLUGIN_SRC, dest)
    except OSError as exc:
        return {"success": False, "message": str(exc), "path": None}
    log.info("Mari bridge installed -> %s", dest)
    return {"success": True, "message": f"installed -> {dest}", "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    f = get_startup_file()
    try:
        if f and f.exists():
            f.unlink()
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "uninstalled"}

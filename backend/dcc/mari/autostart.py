# autostart.py — install the FLUX bridge into Mari's scripts dir (V6 B7).
#
# Same shape as the other DCC autostart modules. Mari evaluates every .py of its user
# scripts dir at startup (<Documents>/Mari/Scripts, next to Mari/Logs); the bridge
# starts its socket server on import.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "mari_bridge.py"
_PLUGIN_NAME = "flux_mari_bridge.py"


# Wrong location used before 2026-09-17: Mari never reads it. Cleaned on (un)install.
_LEGACY_DIR = Path.home() / "Mari" / "Scripts"


def _documents_dir() -> Path:
    return documents_dir()


def _scripts_dir() -> Path:
    """Mari user scripts dir: every .py there is evaluated at Mari startup.

    Order: FLUX_MARI_SCRIPTS_DIR, MARI_SCRIPT_PATH (first entry, Mari's own override),
    then <Documents>/Mari/Scripts (Mari default user path).
    """
    override = os.environ.get("FLUX_MARI_SCRIPTS_DIR")
    if override:
        return Path(override)
    mari_env = os.environ.get("MARI_SCRIPT_PATH", "").split(os.pathsep)[0].strip()
    if mari_env:
        return Path(mari_env)
    return _documents_dir() / "Mari" / "Scripts"


def get_startup_file(exe_path: str | None = None) -> Path | None:
    return _scripts_dir() / _PLUGIN_NAME


def is_installed(exe_path: str | None = None) -> bool:
    f = get_startup_file()
    return bool(f and f.exists())


def _remove_legacy() -> None:
    legacy = _LEGACY_DIR / _PLUGIN_NAME
    if legacy != get_startup_file() and legacy.exists():
        try:
            legacy.unlink()
        except OSError as exc:
            log.warning("Could not remove old Mari bridge %s: %s", legacy, exc)


def install(exe_path: str | None = None) -> dict:
    dest = get_startup_file()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_PLUGIN_SRC, dest)
    except OSError as exc:
        return {"success": False, "message": str(exc), "path": None}
    _remove_legacy()
    log.info("Mari bridge installed -> %s", dest)
    return {"success": True, "message": f"installed -> {dest}", "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    f = get_startup_file()
    try:
        if f and f.exists():
            f.unlink()
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    _remove_legacy()
    return {"success": True, "message": "uninstalled"}

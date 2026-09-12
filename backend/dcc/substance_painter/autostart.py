# autostart.py — install the FLUX bridge plugin into Substance Painter (V6 B2).
#
# Same is_installed / get_startup_file / install / uninstall shape as the other DCC
# autostart modules so the router dispatches generically. Painter loads every .py in
# its user python/plugins dir at launch and calls start_plugin().

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "substance_painter_bridge.py"
_PLUGIN_NAME = "flux_substance_bridge.py"


def _plugins_dir() -> Path:
    """Best-effort Painter user plugins dir (override via FLUX_SP_PLUGINS_DIR)."""
    override = os.environ.get("FLUX_SP_PLUGINS_DIR")
    if override:
        return Path(override)
    docs = Path.home() / "Documents"
    # Latest Painter (Adobe). Older builds used "Allegorithmic/Substance Painter".
    return docs / "Adobe" / "Adobe Substance 3D Painter" / "python" / "plugins"


def get_startup_file(exe_path: str | None = None) -> Path | None:
    return _plugins_dir() / _PLUGIN_NAME


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
    log.info("Substance Painter bridge installed -> %s", dest)
    return {"success": True, "message": f"installed -> {dest}", "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    f = get_startup_file()
    try:
        if f and f.exists():
            f.unlink()
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "uninstalled"}

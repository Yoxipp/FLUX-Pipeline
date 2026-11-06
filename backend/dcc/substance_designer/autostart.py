# autostart.py — install the FLUX bridge plugin into Substance 3D Designer.
#
# Same is_installed / get_startup_file / install / uninstall shape as the other DCC
# autostart modules so the router dispatches generically. Designer loads every plugin
# package of its user plugin dir (python/sduserplugins) at launch and calls
# initializeSDPlugin(); the bridge goes there as a package folder
# (flux_designer_bridge/__init__.py + pluginInfo.json).

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "substance_designer_bridge.py"
_PACKAGE_NAME = "flux_designer_bridge"
_DESIGNER_PLUGINS = ("Adobe", "Adobe Substance 3D Designer", "python", "sduserplugins")
_BRIDGE_LOG = Path(tempfile.gettempdir()) / "flux_designer_bridge.log"
_PLUGIN_INFO = {
    "metadata_format_version": "1",
    "name": "FLUX Bridge",
    "version": "1.0.0",
    "author": "FLUX",
    "email": "",
    "min_designer_version": "11.0",
    "platform": "any",
}


def _plugins_dir() -> Path:
    """Designer user plugin dir (override via FLUX_SD_PLUGINS_DIR), under the REAL
    Documents folder (a redirected Documents is where Designer looks)."""
    override = os.environ.get("FLUX_SD_PLUGINS_DIR")
    if override:
        return Path(override)
    return documents_dir().joinpath(*_DESIGNER_PLUGINS)


def get_startup_file(exe_path: str | None = None) -> Path | None:
    return _plugins_dir() / _PACKAGE_NAME / "__init__.py"


def is_installed(exe_path: str | None = None) -> bool:
    f = get_startup_file()
    return bool(f and f.exists())


def install(exe_path: str | None = None) -> dict:
    dest = get_startup_file()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_PLUGIN_SRC, dest)
        from dcc.bridge_secret import write_sidecar   # secret of the `run` action (__init__.json)
        write_sidecar(dest)
        (dest.parent / "pluginInfo.json").write_text(json.dumps(_PLUGIN_INFO, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": str(exc), "path": None}
    log.info("Substance Designer bridge installed -> %s", dest.parent)
    return {"success": True, "message": f"installed -> {dest.parent}", "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    folder = _plugins_dir() / _PACKAGE_NAME
    try:
        if folder.exists():
            shutil.rmtree(folder)
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "uninstalled"}


def diagnose(max_lines: int = 4) -> str:
    """Why Designer may not answer, in words: where the bridge is and its last log lines."""
    f = get_startup_file()
    parts = [f"Bridge installe dans : {f.parent}" if f.exists()
             else "Bridge non installe (bouton Plug de Designer dans la barre de gauche)"]
    try:
        lines = _BRIDGE_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        lines = []
    if lines:
        parts.append("Log du bridge : " + " / ".join(lines[-max_lines:]))
    elif f.exists():
        parts.append("Designer n'a jamais lance le bridge (aucun log " + str(_BRIDGE_LOG)
                     + ") : relance Designer, verifie Tools > Plugin Manager")
    return ". ".join(parts)

# autostart.py — put the FLUX bridge script where Marvelous Designer can run it.
#
# Same is_installed / get_startup_file / install / uninstall shape as the other DCC
# autostart modules so the router dispatches generically. Marvelous has no startup
# folder FLUX can rely on: the script goes to <Documents>/FLUX/marvelous and the
# artist runs it once per session from Marvelous (Script > Python Script, open the
# file, Run). The Publisher shows that path.

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "marvelous_bridge.py"
_PLUGIN_NAME = "flux_marvelous_bridge.py"
_BRIDGE_LOG = Path(tempfile.gettempdir()) / "flux_marvelous_bridge.log"


def _scripts_dir() -> Path:
    """Where the bridge script lives (override via FLUX_MD_SCRIPTS_DIR)."""
    override = os.environ.get("FLUX_MD_SCRIPTS_DIR")
    if override:
        return Path(override)
    return documents_dir() / "FLUX" / "marvelous"


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
    log.info("Marvelous bridge script installed -> %s", dest)
    return {"success": True, "message": f"installed -> {dest}", "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    f = get_startup_file()
    try:
        if f and f.exists():
            f.unlink()
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "uninstalled"}


def diagnose(max_lines: int = 4) -> str:
    """Why Marvelous may not answer, in words: how to start the bridge and its last log lines."""
    f = get_startup_file()
    if f.exists():
        parts = [f"Dans Marvelous : Script > Python Script, ouvre {f} puis Run (une fois par session)"]
    else:
        parts = ["Script bridge absent (bouton Plug de Marvelous dans la barre de gauche)"]
    try:
        lines = _BRIDGE_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        lines = []
    if lines:
        parts.append("Log du bridge : " + " / ".join(lines[-max_lines:]))
    return ". ".join(parts)

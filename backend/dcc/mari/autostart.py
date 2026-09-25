# autostart.py — install the FLUX bridge into Mari's scripts dirs (V6 B7).
#
# Same shape as the other DCC autostart modules. Mari runs every .py of its user
# scripts dir at startup (Foundry: Documents\Mari\Scripts on Windows, ~/Mari/Scripts
# elsewhere, plus every folder of MARI_SCRIPT_PATH); the bridge starts its socket
# server when Mari runs it.
#
# 2026-09-25: bridge installed, Mari open, dot still orange. FLUX wrote ONE copy,
# into the first MARI_SCRIPT_PATH entry or the shell (OneDrive) Documents folder, which
# is not always the one this Mari reads. The bridge now goes into every folder Mari may
# read (it starts once even when Mari runs two copies), and diagnose() says where it is
# and what its log says when Mari does not answer.

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "mari_bridge.py"
_PLUGIN_NAME = "flux_mari_bridge.py"
_BRIDGE_LOG = Path(tempfile.gettempdir()) / "flux_mari_bridge.log"


def _documents_dir() -> Path:
    return documents_dir()


def _scripts_dirs() -> list[Path]:
    """Every folder Mari may run startup scripts from, most specific first.

    FLUX_MARI_SCRIPTS_DIR alone when set (tests, studio override). Otherwise every
    MARI_SCRIPT_PATH entry, the shell Documents folder (follows OneDrive / GPO
    redirects), the plain profile Documents folder, and ~/Mari/Scripts.
    """
    override = os.environ.get("FLUX_MARI_SCRIPTS_DIR")
    if override:
        return [Path(override)]
    dirs: list[Path] = []
    for entry in os.environ.get("MARI_SCRIPT_PATH", "").split(os.pathsep):
        if entry.strip():
            dirs.append(Path(entry.strip()))
    dirs.append(_documents_dir() / "Mari" / "Scripts")
    dirs.append(Path.home() / "Documents" / "Mari" / "Scripts")
    dirs.append(Path.home() / "Mari" / "Scripts")
    unique: list[Path] = []
    for d in dirs:
        if not any(os.path.normcase(str(d)) == os.path.normcase(str(u)) for u in unique):
            unique.append(d)
    return unique


def _scripts_dir() -> Path:
    """Main scripts dir (the first of _scripts_dirs)."""
    return _scripts_dirs()[0]


def get_startup_file(exe_path: str | None = None) -> Path | None:
    for d in _scripts_dirs():
        f = d / _PLUGIN_NAME
        if f.exists():
            return f
    return _scripts_dir() / _PLUGIN_NAME


def is_installed(exe_path: str | None = None) -> bool:
    return any((d / _PLUGIN_NAME).exists() for d in _scripts_dirs())


def install(exe_path: str | None = None) -> dict:
    written: list[str] = []
    errors: list[str] = []
    for d in _scripts_dirs():
        dest = d / _PLUGIN_NAME
        try:
            d.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_PLUGIN_SRC, dest)
            written.append(str(dest))
        except OSError as exc:              # e.g. a read-only studio MARI_SCRIPT_PATH
            errors.append(f"{dest}: {exc}")
    if not written:
        return {"success": False, "message": "; ".join(errors), "path": None}
    log.info("Mari bridge installed -> %s", ", ".join(written))
    msg = "installed -> " + ", ".join(written)
    if errors:
        msg += " | not written: " + "; ".join(errors)
    return {"success": True, "message": msg, "path": written[0]}


def uninstall(exe_path: str | None = None) -> dict:
    errors: list[str] = []
    for d in _scripts_dirs():
        f = d / _PLUGIN_NAME
        try:
            if f.exists():
                f.unlink()
        except OSError as exc:
            errors.append(str(exc))
    if errors:
        return {"success": False, "message": "; ".join(errors)}
    return {"success": True, "message": "uninstalled"}


def diagnose(max_lines: int = 4) -> str:
    """Why Mari may not answer, in words: where the bridge is and its last log lines."""
    installed = [str(d / _PLUGIN_NAME) for d in _scripts_dirs() if (d / _PLUGIN_NAME).exists()]
    parts = []
    if installed:
        parts.append("Bridge installe dans : " + ", ".join(installed))
    else:
        parts.append("Bridge non installe (bouton Plug de Mari dans la barre de gauche)")
    try:
        lines = _BRIDGE_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        lines = []
    if lines:
        parts.append("Log du bridge : " + " / ".join(lines[-max_lines:]))
    elif installed:
        parts.append("Mari n'a jamais lance le bridge (aucun log " + str(_BRIDGE_LOG)
                     + ") : relance Mari apres l'installation")
    return ". ".join(parts)

# autostart.py — install the FLUX bridge plugin into Substance Painter (V6 B2).
#
# Same is_installed / get_startup_file / install / uninstall shape as the other DCC
# autostart modules so the router dispatches generically. Painter starts every module
# of its user python/startup dir at launch (start_plugin()); python/plugins modules only
# run once ticked in the Python menu, so older installs there are moved to startup.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "substance_painter_bridge.py"
_PLUGIN_NAME = "flux_substance_bridge.py"
_PAINTER_PYTHON = ("Adobe", "Adobe Substance 3D Painter", "python")
_PAINTER_PLUGINS = (*_PAINTER_PYTHON, "startup")
# Before 2026-09-24 the bridge went to python/plugins (never started on its own).
_OLD_SUBDIR = "plugins"


def _plugins_dir() -> Path:
    """Painter user plugins dir (override via FLUX_SP_PLUGINS_DIR).

    Under the REAL Documents folder: a redirected Documents (OneDrive, custom path)
    is where Painter looks, not ~/Documents.
    """
    override = os.environ.get("FLUX_SP_PLUGINS_DIR")
    if override:
        return Path(override)
    # Latest Painter (Adobe). Older builds used "Allegorithmic/Substance Painter".
    return documents_dir().joinpath(*_PAINTER_PLUGINS)


def _legacy_files() -> list[Path]:
    """Copies left by older FLUX builds: ~/Documents (never read when redirected) and
    python/plugins (needs a manual tick in Painter)."""
    return [
        (Path.home() / "Documents").joinpath(*_PAINTER_PLUGINS) / _PLUGIN_NAME,
        (Path.home() / "Documents").joinpath(*_PAINTER_PYTHON, _OLD_SUBDIR) / _PLUGIN_NAME,
        _plugins_dir().parent / _OLD_SUBDIR / _PLUGIN_NAME,
    ]


def get_startup_file(exe_path: str | None = None) -> Path | None:
    return _plugins_dir() / _PLUGIN_NAME


def is_installed(exe_path: str | None = None) -> bool:
    f = get_startup_file()
    return bool(f and f.exists())


def _remove_legacy() -> None:
    for legacy in _legacy_files():
        if legacy != get_startup_file() and legacy.exists():
            try:
                legacy.unlink()
            except OSError as exc:
                log.warning("Could not remove old Painter bridge %s: %s", legacy, exc)


def install(exe_path: str | None = None) -> dict:
    dest = get_startup_file()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_PLUGIN_SRC, dest)
    except OSError as exc:
        return {"success": False, "message": str(exc), "path": None}
    _remove_legacy()
    log.info("Substance Painter bridge installed -> %s", dest)
    # The studio export presets come with the bridge (2026-09-26).
    from dcc.substance_painter.presets import install_presets
    presets = install_presets()
    msg = f"installed -> {dest}" + (f" | {len(presets)} preset(s) d'export" if presets else "")
    return {"success": True, "message": msg, "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    f = get_startup_file()
    try:
        if f and f.exists():
            f.unlink()
    except OSError as exc:
        return {"success": False, "message": str(exc)}
    _remove_legacy()
    return {"success": True, "message": "uninstalled"}

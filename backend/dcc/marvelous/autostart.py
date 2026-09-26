# autostart.py — install the FLUX bridge script into Marvelous Designer's Plug-in menu.
#
# Same is_installed / get_startup_file / install / uninstall shape as the other DCC
# autostart modules so the router dispatches generically. Marvelous has no startup
# script FLUX can rely on, and its Python only runs while a script executes, so the
# bridge is a script that keeps running once started. install() copies it to
# <Documents>/FLUX/marvelous and registers it in Marvelous' Plug-in Manager
# (pluginSettings.json, same entry as Plug-in Manager > +ADD): the artist then starts
# it with one click, Plugins > Plug-in > FLUX Bridge, once per session.
#
# pluginSettings.json lives in the PUBLIC Documents folder on Windows
# (C:/Users/Public/Documents/MarvelousDesigner/Plugins), ~/Documents elsewhere.
# Marvelous may rewrite it on exit: register while Marvelous is closed.

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from core.logger import get_logger
from dcc.user_dirs import documents_dir

log = get_logger(__name__)

_PLUGIN_SRC = Path(__file__).resolve().parent / "marvelous_bridge.py"
_PLUGIN_NAME = "flux_marvelous_bridge.py"
_PLUGIN_TITLE = "FLUX Bridge"
_MENU = "Plugins / Plug-in"
_SETTINGS_NAME = "pluginSettings.json"
_BRIDGE_LOG = Path(tempfile.gettempdir()) / "flux_marvelous_bridge.log"


def _scripts_dir() -> Path:
    """Where the bridge script lives (override via FLUX_MD_SCRIPTS_DIR)."""
    override = os.environ.get("FLUX_MD_SCRIPTS_DIR")
    if override:
        return Path(override)
    return documents_dir() / "FLUX" / "marvelous"


def _plugins_dir() -> Path:
    """Marvelous' plug-in settings folder (override via FLUX_MD_PLUGINS_DIR)."""
    override = os.environ.get("FLUX_MD_PLUGINS_DIR")
    if override:
        return Path(override)
    if os.name == "nt":
        public = os.environ.get("PUBLIC") or r"C:\Users\Public"
        return Path(public) / "Documents" / "MarvelousDesigner" / "Plugins"
    return Path.home() / "Documents" / "MarvelousDesigner" / "Plugins"


def _same_path(a: str, b: str) -> bool:
    return a.replace("\\", "/").lower() == b.replace("\\", "/").lower()


def _read_settings(path: Path) -> dict:
    """pluginSettings.json content; a missing file is an empty registry. Raises
    ValueError when the file exists but is not a registry (never overwritten then)."""
    if not path.exists():
        return {"plugins": [], "version": 2}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("plugins", []), list):
        raise ValueError(f"{path} n'a pas le format attendu")
    data.setdefault("plugins", [])
    return data


def register_plugin(script: Path, settings_path: Path | None = None) -> str:
    """Add *script* to the Plug-in menu (idempotent). Returns the settings file path."""
    settings_path = settings_path or _plugins_dir() / _SETTINGS_NAME
    data = _read_settings(settings_path)
    plugins = [p for p in data["plugins"]
               if not (isinstance(p, dict) and (_same_path(str(p.get("m_SourcePath", "")), str(script))
                                                or p.get("m_PlugInTitle") == _PLUGIN_TITLE))]
    plugins.append({
        "m_AddingPositionIndex": len(plugins),
        "m_BaseMenuTreeByObjectName": _MENU,
        "m_PlugInFileName": str(script),
        "m_PlugInIconFileName": "",
        "m_PlugInTitle": _PLUGIN_TITLE,
        "m_SourcePath": str(script),
        "m_SourceType": "script",
    })
    data["plugins"] = plugins
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = settings_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
    os.replace(tmp, settings_path)
    return str(settings_path)


def unregister_plugin(settings_path: Path | None = None) -> None:
    settings_path = settings_path or _plugins_dir() / _SETTINGS_NAME
    if not settings_path.exists():
        return
    data = _read_settings(settings_path)
    kept = [p for p in data["plugins"] if not (isinstance(p, dict) and p.get("m_PlugInTitle") == _PLUGIN_TITLE)]
    if len(kept) != len(data["plugins"]):
        data["plugins"] = kept
        settings_path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def is_registered() -> bool:
    try:
        data = _read_settings(_plugins_dir() / _SETTINGS_NAME)
    except (OSError, ValueError):
        return False
    return any(isinstance(p, dict) and p.get("m_PlugInTitle") == _PLUGIN_TITLE for p in data["plugins"])


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
    try:
        settings = register_plugin(dest)
        log.info("Marvelous bridge registered in %s", settings)
        msg = (f"installed -> {dest}. Dans Marvelous (a relancer s'il est ouvert) : "
               f"Plugins > Plug-in > {_PLUGIN_TITLE}")
    except (OSError, ValueError) as exc:
        # The script works without the menu entry: Plug-in Manager > +ADD by hand.
        log.warning("Marvelous plug-in registration failed: %s", exc)
        msg = (f"installed -> {dest}. Menu Plug-in non ecrit ({exc}) : "
               f"Plugins > Plug-in Manager > +ADD, choisis ce fichier")
    return {"success": True, "message": msg, "path": str(dest)}


def uninstall(exe_path: str | None = None) -> dict:
    f = get_startup_file()
    try:
        if f and f.exists():
            f.unlink()
        unregister_plugin()
    except (OSError, ValueError) as exc:
        return {"success": False, "message": str(exc)}
    return {"success": True, "message": "uninstalled"}


def python_editor_line() -> str:
    """One line to paste in Marvelous' Python editor to start the bridge by hand.

    No double quote and no backslash: the Marvelous 2024 editor mangles them (a bare
    Windows path or a r"..." string gave "unexpected character after line
    continuation character"). Forward slashes work on Windows."""
    path = str(get_startup_file()).replace("\\", "/")
    return f"exec(open('{path}').read())"


def diagnose(max_lines: int = 4) -> str:
    """Why Marvelous may not answer, in words: how to start the bridge and its last log lines."""
    f = get_startup_file()
    if not f.exists():
        parts = ["Bridge absent (bouton Plug de Marvelous dans la barre de gauche)"]
    elif is_registered():
        parts = [f"Dans Marvelous : Plugins > Plug-in > {_PLUGIN_TITLE} (une fois par session)"]
    else:
        parts = [f"Dans Marvelous : Script > Python (Plugins > Python Editor en 2024.1+), "
                 f"colle {python_editor_line()} puis Run"]
    try:
        lines = _BRIDGE_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    except OSError:
        lines = []
    if lines:
        parts.append("Log du bridge : " + " / ".join(lines[-max_lines:]))
    return ". ".join(parts)

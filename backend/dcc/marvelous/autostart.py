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
#
# Marvelous 2024 embeds the official python.org Python 3.7 build WITHOUT _ctypes, so
# the bridge cannot pump Marvelous' window messages (one-shot mode: Marvelous busy
# until the first export). install() also fetches the matching official embeddable
# Python 3.7.9 (python.org, PSF license) and keeps only _ctypes.pyd + libffi-7.dll in
# %LOCALAPPDATA%/FLUX/marvelous_pylib, where the bridge looks for them. No network:
# the bridge still works, one-shot.

from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import urllib.request
import zipfile
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
# Same CPython 3.7 ABI as Marvelous 2024 (its log says "python 3.7.9").
_PYLIB_URL = "https://www.python.org/ftp/python/3.7.9/python-3.7.9-embed-amd64.zip"
_PYLIB_FILES = ("_ctypes.pyd", "libffi-7.dll")


def pylib_dir() -> Path:
    """Where the bridge finds _ctypes (same rule as marvelous_bridge.PYLIB)."""
    root = os.environ.get("LOCALAPPDATA") or str(Path.home())
    return Path(root) / "FLUX" / "marvelous_pylib"


def has_pylib() -> bool:
    return all((pylib_dir() / f).is_file() for f in _PYLIB_FILES)


def ensure_pylib(url: str | None = None, timeout: float = 60.0) -> str:
    """Fetch _ctypes for Marvelous' Python once; returns what happened, in words."""
    if has_pylib():
        return "ctypes deja present"
    url = url or os.environ.get("FLUX_MD_PYLIB_URL") or _PYLIB_URL
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            data = resp.read()
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = {Path(n).name: n for n in zf.namelist()}
            missing = [f for f in _PYLIB_FILES if f not in names]
            if missing:
                return f"ctypes non installe ({', '.join(missing)} absent de {url})"
            dest = pylib_dir()
            dest.mkdir(parents=True, exist_ok=True)
            for f in _PYLIB_FILES:
                (dest / f).write_bytes(zf.read(names[f]))
            # The ctypes package (compiled for this exact Python) from the zip's
            # stdlib, in case Marvelous dropped it along with _ctypes.
            stdlib = next((n for n in zf.namelist() if Path(n).name.startswith("python3")
                           and n.endswith(".zip")), None)
            if stdlib:
                with zipfile.ZipFile(io.BytesIO(zf.read(stdlib))) as lib:
                    for n in lib.namelist():
                        if n.startswith("ctypes/") and not n.startswith("ctypes/test/") and not n.endswith("/"):
                            target = dest / n
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(lib.read(n))
    except (OSError, zipfile.BadZipFile, ValueError) as exc:
        log.warning("Marvelous ctypes download failed: %s", exc)
        return f"ctypes non telecharge ({exc}) : Marvelous restera occupe jusqu'au premier export"
    log.info("Marvelous ctypes installed -> %s", pylib_dir())
    return "ctypes installe"


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
    pylib = ensure_pylib() if os.name == "nt" or os.environ.get("FLUX_MD_PYLIB_URL") else "ctypes: Windows seulement"
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
    return {"success": True, "message": f"{msg}. {pylib}", "path": str(dest)}


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
    else:
        # Marvelous 2024 has no Plug-in menu (2024.1+): both ways, the 2024 one first.
        parts = [f"Dans Marvelous 2024 : Script > Python, colle {python_editor_line()} puis Run"
                 + (f" ; 2024.1+ : Plugins > Plug-in > {_PLUGIN_TITLE}" if is_registered() else "")
                 + " (une fois par session)"]
        if os.name == "nt" and not has_pylib():
            parts.append("ctypes absent : Marvelous occupe jusqu'au premier export (rebranche le Plug avec internet)")
    try:
        lines = [ln for ln in _BRIDGE_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
                 if "export functions:" not in ln]        # the inventory line is long
    except OSError:
        lines = []
    if lines:
        parts.append("Log du bridge : " + " / ".join(lines[-max_lines:]))
    return ". ".join(parts)

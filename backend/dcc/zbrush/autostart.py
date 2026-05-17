"""
FLUX — ZBrush plugin autostart manager.

Implements BOTH official ZBrush Python plugin loading mechanisms:

  Mechanism 1 — PYTHONPATH + init.py  (recommended by official ZBrush 2026.1 docs)
    ZBrush scans PYTHONPATH at startup, runs init.py from each sub-directory found.
    Equivalent to Houdini's 123.py.
    Install target : <zbrush_data_dir>\FluxBridge\init.py
    PYTHONPATH entry: <zbrush_data_dir>  (parent of FluxBridge\)

  Mechanism 2 — ZBRUSH_PLUGIN_PATH + *.py  (fallback)
    ZBrush runs ALL *.py found in ZPlugs64 at startup.
    Install target : <zbrush_data_dir>\ZStartup\ZPlugs64\zbrush_bridge_plugin.py

Both mechanisms are used simultaneously so the plugin loads regardless of
which one ZBrush honours on the user's setup.

Works for any user on any machine with ZBrush 2024+ installed. No hardcoded paths.
"""

from __future__ import annotations

import os
import platform
import shutil
from pathlib import Path


def _get_documents_dir() -> Path:
    """Return the real Windows Documents folder, honouring GPO/OneDrive redirects."""
    if platform.system() != "Windows":
        return Path.home() / "Documents"
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        val, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        return Path(val)
    except Exception:
        return Path.home() / "Documents"


def _find_zbrush_data_dirs() -> list[Path]:
    """
    Return all ZBrush user-data root directories found on this machine.
    Sorted newest first (highest version number / most recent hash).

    ZBrush 2024+ (Maxon): %APPDATA%\\Maxon\\Maxon ZBrush YYYY_HASH\\
    Classic             : %USERPROFILE%\\Documents\\ZBrushData*\\
    """
    roots: list[Path] = []
    system = platform.system()

    if system == "Windows":
        # ZBrush 2024+ (Maxon) — primary location
        appdata = Path(os.environ.get("APPDATA", ""))
        maxon_dir = appdata / "Maxon"
        if maxon_dir.exists():
            try:
                for d in sorted(maxon_dir.glob("Maxon ZBrush*"), reverse=True):
                    if d.is_dir():
                        roots.append(d)
            except OSError:
                pass

        # Classic Documents location — fallback
        docs = _get_documents_dir()
        try:
            for d in sorted(docs.glob("ZBrushData*"), reverse=True):
                if d.is_dir():
                    roots.append(d)
        except OSError:
            pass

        # Absolute fallback (neither exists yet)
        if not roots:
            roots.append(appdata / "Maxon" / "Maxon ZBrush")

    elif system == "Darwin":
        base = Path.home() / "Library" / "Application Support" / "ZBrush"
        roots.append(base)
    else:
        roots.append(Path.home() / ".zbrush")

    return roots


# ── Path helpers ──────────────────────────────────────────────────────────────

_PLUGIN_SRC        = Path(__file__).parent / "zbrush_bridge_plugin.py"
_FLUX_BRIDGE_DIR   = "FluxBridge"   # sub-dir for PYTHONPATH mechanism
_FLUX_BRIDGE_INIT  = "init.py"      # entry point for PYTHONPATH mechanism
_PLUGS64_FILENAME  = "zbrush_bridge_plugin.py"  # for ZBRUSH_PLUGIN_PATH mechanism


def _plugs64_dirs() -> list[Path]:
    """ZPlugs64 dirs for all discovered ZBrush installs."""
    return [r / "ZStartup" / "ZPlugs64" for r in _find_zbrush_data_dirs()]


def _flux_bridge_init_paths() -> list[tuple[Path, Path]]:
    """[(init_file_path, pythonpath_entry), ...] for each ZBrush install."""
    result: list[tuple[Path, Path]] = []
    for root in _find_zbrush_data_dirs():
        init_file     = root / _FLUX_BRIDGE_DIR / _FLUX_BRIDGE_INIT
        pythonpath_entry = root                 # parent of FluxBridge\
        result.append((init_file, pythonpath_entry))
    return result


# ── Windows PYTHONPATH registry helpers ───────────────────────────────────────

def _get_user_pythonpath() -> str:
    """Read current user-level PYTHONPATH from the Windows registry."""
    if platform.system() != "Windows":
        return os.environ.get("PYTHONPATH", "")
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
        val, _ = winreg.QueryValueEx(key, "PYTHONPATH")
        winreg.CloseKey(key)
        return val or ""
    except Exception:
        return os.environ.get("PYTHONPATH", "")


def _set_user_pythonpath(value: str) -> None:
    """Write user-level PYTHONPATH to the Windows registry."""
    if platform.system() != "Windows":
        return
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, "PYTHONPATH", 0, winreg.REG_EXPAND_SZ, value)
        winreg.CloseKey(key)
    except Exception:
        pass


def _add_to_pythonpath(new_entry: Path) -> None:
    """Add *new_entry* to the user-level PYTHONPATH if not already present."""
    entry_str = str(new_entry)
    current   = _get_user_pythonpath()
    parts     = [p for p in current.split(os.pathsep) if p]
    if entry_str not in parts:
        parts.append(entry_str)
        _set_user_pythonpath(os.pathsep.join(parts))


def _remove_from_pythonpath(entry: Path) -> None:
    """Remove *entry* from the user-level PYTHONPATH."""
    entry_str = str(entry)
    current   = _get_user_pythonpath()
    parts     = [p for p in current.split(os.pathsep) if p and p != entry_str]
    _set_user_pythonpath(os.pathsep.join(parts))


# ── Install / uninstall ───────────────────────────────────────────────────────

def install_plugin() -> dict:
    """
    Install the FLUX bridge plugin using BOTH mechanisms:
      1. PYTHONPATH + init.py  → <zbrush_root>/FluxBridge/init.py  + PYTHONPATH entry
      2. ZBRUSH_PLUGIN_PATH   → <zbrush_root>/ZStartup/ZPlugs64/zbrush_bridge_plugin.py

    Returns {"ok": bool, "path": str | None, "paths": list[str], "error": str | None}.
    """
    if not _PLUGIN_SRC.exists():
        return {"ok": False, "path": None, "paths": [], "error": f"Source not found: {_PLUGIN_SRC}"}

    installed: list[str] = []
    errors:    list[str] = []

    # ── Mechanism 1: PYTHONPATH + init.py ─────────────────────────────────────
    for init_path, pythonpath_entry in _flux_bridge_init_paths():
        try:
            init_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_PLUGIN_SRC, init_path)
            installed.append(str(init_path))
            _add_to_pythonpath(pythonpath_entry)
        except OSError as exc:
            errors.append(f"PYTHONPATH install {init_path}: {exc}")

    # ── Mechanism 2: ZPlugs64 ─────────────────────────────────────────────────
    for plugs64 in _plugs64_dirs():
        dest = plugs64 / _PLUGS64_FILENAME
        if dest in [Path(p) for p in installed]:
            continue  # already installed by mechanism 1 to same path (unlikely)
        try:
            plugs64.mkdir(parents=True, exist_ok=True)
            shutil.copy2(_PLUGIN_SRC, dest)
            installed.append(str(dest))
        except OSError as exc:
            errors.append(f"ZPlugs64 install {dest}: {exc}")

    if installed:
        return {"ok": True, "path": installed[0], "paths": installed, "error": None}
    return {"ok": False, "path": None, "paths": [], "error": "; ".join(errors) or "No ZBrush install found"}


def uninstall_plugin() -> dict:
    """Remove the FLUX bridge plugin from all install locations and clean PYTHONPATH."""
    removed: list[str] = []
    errors:  list[str] = []

    # ── Mechanism 1: FluxBridge/init.py + PYTHONPATH ──────────────────────────
    for init_path, pythonpath_entry in _flux_bridge_init_paths():
        if init_path.exists():
            try:
                init_path.unlink()
                removed.append(str(init_path))
                # Remove parent FluxBridge/ dir if now empty
                try:
                    init_path.parent.rmdir()
                except OSError:
                    pass
            except OSError as exc:
                errors.append(str(exc))
        _remove_from_pythonpath(pythonpath_entry)

    # ── Mechanism 2: ZPlugs64 ─────────────────────────────────────────────────
    for plugs64 in _plugs64_dirs():
        dest = plugs64 / _PLUGS64_FILENAME
        if dest.exists():
            try:
                dest.unlink()
                removed.append(str(dest))
            except OSError as exc:
                errors.append(str(exc))

    if errors:
        return {"ok": False, "message": "; ".join(errors)}
    return {"ok": True, "message": "uninstalled" if removed else "not_installed"}


def get_plugin_status() -> dict:
    """Check if the plugin is installed via either mechanism."""
    installed_in: list[str] = []

    for init_path, _ in _flux_bridge_init_paths():
        if init_path.exists():
            installed_in.append(str(init_path))

    for plugs64 in _plugs64_dirs():
        dest = plugs64 / _PLUGS64_FILENAME
        if dest.exists():
            installed_in.append(str(dest))

    primary = installed_in[0] if installed_in else None
    return {
        "plugin_dir":   str(Path(primary).parent) if primary else None,
        "installed":    len(installed_in) > 0,
        "dest_path":    primary,
        "installed_in": installed_in,
    }


def get_zbrush_plugin_dir() -> Path | None:
    """Return the primary ZBrush plugin directory (first existing install location)."""
    status = get_plugin_status()
    dest   = status.get("dest_path")
    return Path(dest).parent if dest else None


# ── Router-compatible interface ───────────────────────────────────────────────

def is_installed(_exe_path: str | None = None) -> bool:
    return get_plugin_status()["installed"]


def get_startup_file(_exe_path: str | None = None) -> "Path | None":
    status = get_plugin_status()
    dest   = status.get("dest_path")
    return Path(dest) if dest else None


def install(_exe_path: str | None = None) -> dict:
    result = install_plugin()
    paths  = result.get("paths", [])
    msg    = result.get("error") or (
        f"Installed ({len(paths)} location(s)) — restart ZBrush to activate"
        if paths else "failed"
    )
    return {"success": result["ok"], "message": msg, "path": result.get("path")}


def uninstall(_exe_path: str | None = None) -> dict:
    result = uninstall_plugin()
    return {"success": result.get("ok", False), "message": result.get("message", "")}

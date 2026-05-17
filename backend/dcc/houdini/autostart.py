"""
FLUX — Houdini 123.py autostart manager.
Installs / removes the FLUX server block in Houdini's startup script.
Works without Houdini being open.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
from pathlib import Path

# Markers used to locate the FLUX block in 123.py — never change these.
_BLOCK_BEGIN = "# >>> FLUX autostart — do not edit manually"
_BLOCK_END   = "# <<< FLUX autostart"


# ---------------------------------------------------------------------------
# Prefs / startup file location
# ---------------------------------------------------------------------------

def _try_hconfig(houdini_exe_path: str | None = None) -> Path | None:
    """Run hconfig -ap to resolve HOUDINI_USER_PREF_DIR via Houdini's own env resolution."""
    hconfig_candidates: list[str | Path] = []
    if houdini_exe_path:
        hconfig_candidates.append(Path(houdini_exe_path).parent / "hconfig.exe")
    hconfig_candidates.append("hconfig")  # Houdini Shell PATH fallback

    # CREATE_NO_WINDOW — évite une console visible sur Windows (meilleure pratique)
    extra: dict = {}
    if platform.system() == "Windows":
        extra["creationflags"] = 0x08000000  # CREATE_NO_WINDOW

    for hconfig in hconfig_candidates:
        try:
            result = subprocess.run(
                [str(hconfig), "-ap"],
                capture_output=True, text=True, timeout=10,
                **extra,
            )
            for line in result.stdout.splitlines():
                if "HOUDINI_USER_PREF_DIR" in line:
                    parts = line.split(":=", 1)
                    if len(parts) == 2:
                        p = Path(parts[1].strip())
                        if p.exists():
                            return p
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue
    return None


def _default_prefs_path(houdini_exe_path: str | None = None) -> Path | None:
    """OS-specific default prefs path. Version extracted from exe path via regex."""
    version: str | None = None
    if houdini_exe_path:
        m = re.search(r"[Hh]oudini(?:\s+(?:FX|Core|Indie|Apprentice))?\s+(\d+\.\d+)", str(houdini_exe_path))
        if m:
            version = m.group(1)

    system = platform.system()

    if system == "Windows":
        home = Path.home()
        # Prefs can be in Documents OR directly in home (non-standard but documented by SideFX)
        if version:
            for base in (home / "Documents", home):
                p = base / f"houdini{version}"
                if p.exists():
                    return p
        candidates: list[Path] = []
        for base in (home / "Documents", home):
            try:
                candidates.extend(
                    d for d in base.glob("houdini*")
                    if d.is_dir() and re.match(r"houdini\d+\.\d+$", d.name)
                )
            except OSError:
                pass
        candidates.sort(key=lambda d: d.name, reverse=True)
        return candidates[0] if candidates else None

    elif system == "Darwin":
        prefs = Path.home() / "Library" / "Preferences" / "houdini"
        if version:
            p = prefs / version
            if p.exists():
                return p
        if prefs.exists():
            mac_candidates = sorted(
                [d for d in prefs.iterdir() if d.is_dir() and re.match(r"\d+\.\d+$", d.name)],
                key=lambda d: d.name, reverse=True,
            )
            return mac_candidates[0] if mac_candidates else None
        return None

    else:  # Linux
        home = Path.home()
        if version:
            p = home / f"houdini{version}"
            if p.exists():
                return p
        linux_candidates = sorted(
            [d for d in home.glob("houdini*") if d.is_dir() and re.match(r"houdini\d+\.\d+$", d.name)],
            key=lambda d: d.name, reverse=True,
        )
        return linux_candidates[0] if linux_candidates else None


def get_prefs_dir(houdini_exe_path: str | None = None) -> Path | None:
    """
    Locate Houdini's user prefs directory without running Houdini.

    Search order:
      1. HOUDINI_USER_PREF_DIR env var
      2. hconfig -ap  (official SideFX utility — handles GPO-redirected paths and custom installs)
      3. OS-default paths (Windows ~/Documents/houdiniX.Y or ~/houdiniX.Y,
                           macOS ~/Library/Preferences/houdini/X.Y, Linux ~/houdiniX.Y)
    """
    env = os.environ.get("HOUDINI_USER_PREF_DIR")
    if env:
        p = Path(env)
        if p.exists():
            return p

    # Chemins par défaut OS — couvre les installations standard, aucun subprocess
    default = _default_prefs_path(houdini_exe_path)
    if default:
        return default

    # Dernier recours : hconfig (installations non-standard, redirections GPO…)
    # Déclenche une création de processus — peut alerter certains antivirus.
    return _try_hconfig(houdini_exe_path)


def get_startup_file(houdini_exe_path: str | None = None) -> Path | None:
    """Return the 123.py path (may not exist yet). None if prefs dir not found."""
    prefs = get_prefs_dir(houdini_exe_path)
    return (prefs / "scripts" / "123.py") if prefs else None


# ---------------------------------------------------------------------------
# Server script deployment
# ---------------------------------------------------------------------------

def _get_deploy_dir() -> Path:
    """%APPDATA%/FLUX/dcc/houdini/ — created on first call."""
    appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    deploy = Path(appdata) / "FLUX" / "dcc" / "houdini"
    deploy.mkdir(parents=True, exist_ok=True)
    return deploy


def _deploy_server() -> Path:
    """
    Copy flux_houdini_server.py to AppData so Houdini can always find it,
    even if the FLUX install directory changes. Returns the deploy dir.
    """
    src = Path(__file__).parent / "flux_houdini_server.py"
    deploy_dir = _get_deploy_dir()
    shutil.copy2(src, deploy_dir / "flux_houdini_server.py")
    return deploy_dir


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_installed(houdini_exe_path: str | None = None) -> bool:
    startup = get_startup_file(houdini_exe_path)
    if startup is None or not startup.exists():
        return False
    try:
        return _BLOCK_BEGIN in startup.read_text(encoding="utf-8")
    except OSError:
        return False


def install(houdini_exe_path: str | None = None) -> dict:
    """
    Deploy flux_houdini_server.py to AppData and append autostart block to 123.py.
    Idempotent — safe to call multiple times.

    Returns {"success": bool, "message": str, "path": str | None}
    """
    startup = get_startup_file(houdini_exe_path)
    if startup is None:
        return {"success": False, "message": "Houdini prefs directory not found", "path": None}

    # Deploy server to a stable AppData path
    try:
        deploy_dir = _deploy_server()
    except Exception as exc:
        return {"success": False, "message": f"Failed to deploy server: {exc}", "path": None}

    # Use forward slashes — safe on Windows in Python code strings
    server_dir = str(deploy_dir).replace("\\", "/")

    # Ensure scripts/ dir exists
    startup.parent.mkdir(parents=True, exist_ok=True)

    existing = startup.read_text(encoding="utf-8") if startup.exists() else ""
    if _BLOCK_BEGIN in existing:
        # Auto-upgrade: si l'ancien bloc n'a pas le try/except de sécurité, le remplacer
        b_start = existing.find(_BLOCK_BEGIN)
        b_end   = existing.find(_BLOCK_END, b_start)
        old_fragment = existing[b_start : b_end + len(_BLOCK_END)] if b_end > b_start else ""
        if "try:" not in old_fragment:
            new_fragment = (
                f"{_BLOCK_BEGIN}\n"
                f"try:\n"
                f"    import sys as _flux_sys\n"
                f"    _flux_sys.path.insert(0, {repr(server_dir)})\n"
                f"    import flux_houdini_server\n"
                f"except Exception as _flux_exc:\n"
                f"    print(f'[FLUX] Autostart error (Houdini continues normally): {{_flux_exc}}')\n"
                f"{_BLOCK_END}"
            )
            try:
                startup.write_text(existing.replace(old_fragment, new_fragment), encoding="utf-8")
            except OSError as exc:
                return {"success": False, "message": f"Cannot upgrade 123.py: {exc}", "path": str(startup)}
            return {"success": True, "message": f"upgraded: {startup}", "path": str(startup)}
        return {"success": True, "message": "already_installed", "path": str(startup)}

    block = (
        f"\n{_BLOCK_BEGIN}\n"
        f"try:\n"
        f"    import sys as _flux_sys\n"
        f"    _flux_sys.path.insert(0, {repr(server_dir)})\n"
        f"    import flux_houdini_server\n"
        f"except Exception as _flux_exc:\n"
        f"    print(f'[FLUX] Autostart error (Houdini continues normally): {{_flux_exc}}')\n"
        f"{_BLOCK_END}\n"
    )
    try:
        with open(startup, "a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError as exc:
        return {"success": False, "message": f"Cannot write 123.py: {exc}", "path": str(startup)}

    return {"success": True, "message": f"installed: {startup}", "path": str(startup)}


def uninstall(houdini_exe_path: str | None = None) -> dict:
    """
    Remove the FLUX autostart block from 123.py.
    Leaves all other content untouched.

    Returns {"success": bool, "message": str}
    """
    startup = get_startup_file(houdini_exe_path)
    if startup is None or not startup.exists():
        return {"success": True, "message": "not_installed"}

    try:
        content = startup.read_text(encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": f"Cannot read 123.py: {exc}"}

    if _BLOCK_BEGIN not in content:
        return {"success": True, "message": "not_installed"}

    cleaned = re.sub(
        rf"\n?{re.escape(_BLOCK_BEGIN)}.*?{re.escape(_BLOCK_END)}\n?",
        "",
        content,
        flags=re.DOTALL,
    )
    try:
        startup.write_text(cleaned, encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": f"Cannot write 123.py: {exc}"}

    return {"success": True, "message": "uninstalled"}

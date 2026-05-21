# autostart.py — FLUX Maya userSetup.py manager.
# Installs / removes the FLUX autostart block in Maya's userSetup.py.
# Works without Maya being open.

from __future__ import annotations

import platform
import re
import shutil
from pathlib import Path

# Markers — never change these; they identify the FLUX block in userSetup.py.
_BLOCK_BEGIN = "# >>> FLUX autostart — do not edit manually"
_BLOCK_END   = "# <<< FLUX autostart"

# flux_bridge.py source (deployed next to userSetup.py)
_BRIDGE_SRC = Path(__file__).parent / "startup" / "flux_bridge.py"


# ── Prefs / startup file location ────────────────────────────────────────────

def _get_documents_dir() -> Path:
    """Return the real Windows Documents folder (handles GPO/OneDrive redirects)."""
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


def _extract_version(maya_exe_path: str) -> str | None:
    """Extract 4-digit Maya version from exe path, e.g. 'Maya 2024' → '2024'."""
    m = re.search(r"[Mm]aya\D*(\d{4})", str(maya_exe_path))
    return m.group(1) if m else None


def _find_prefs_dir(maya_exe_path: str | None = None) -> Path | None:
    """Locate Maya's per-user prefs directory without running Maya."""
    system = platform.system()
    version = _extract_version(maya_exe_path) if maya_exe_path else None

    if system == "Windows":
        docs = _get_documents_dir()
        base = docs / "maya"
        if version:
            candidate = base / version
            if candidate.exists():
                return candidate
        # Glob all maya/20xx versions, descending
        try:
            candidates = sorted(
                [d for d in base.glob("20*") if d.is_dir()],
                key=lambda d: d.name, reverse=True,
            )
            return candidates[0] if candidates else None
        except OSError:
            return None

    elif system == "Darwin":
        base = Path.home() / "Library" / "Preferences" / "Autodesk" / "maya"
        if version:
            candidate = base / version
            if candidate.exists():
                return candidate
        try:
            candidates = sorted(
                [d for d in base.glob("20*") if d.is_dir()],
                key=lambda d: d.name, reverse=True,
            )
            return candidates[0] if candidates else None
        except OSError:
            return None

    else:  # Linux
        base = Path.home() / "maya"
        if version:
            candidate = base / version
            if candidate.exists():
                return candidate
        try:
            candidates = sorted(
                [d for d in base.glob("20*") if d.is_dir()],
                key=lambda d: d.name, reverse=True,
            )
            return candidates[0] if candidates else None
        except OSError:
            return None


def get_startup_file(maya_exe_path: str | None = None) -> Path | None:
    """Return the userSetup.py path (may not exist yet). None if prefs dir not found."""
    prefs = _find_prefs_dir(maya_exe_path)
    return (prefs / "scripts" / "userSetup.py") if prefs else None


# ── Public API ────────────────────────────────────────────────────────────────

def is_installed(maya_exe_path: str | None = None) -> bool:
    startup = get_startup_file(maya_exe_path)
    if startup is None or not startup.exists():
        return False
    try:
        return _BLOCK_BEGIN in startup.read_text(encoding="utf-8")
    except OSError:
        return False


def install(maya_exe_path: str | None = None) -> dict:
    """Deploy flux_bridge.py and append/upgrade the FLUX block in userSetup.py.

    Idempotent — safe to call multiple times.
    Returns {"success": bool, "message": str, "path": str | None}
    """
    startup = get_startup_file(maya_exe_path)
    if startup is None:
        return {"success": False, "message": "Maya prefs directory not found", "path": None}

    scripts_dir = startup.parent
    scripts_dir.mkdir(parents=True, exist_ok=True)

    # Deploy flux_bridge.py next to userSetup.py
    try:
        shutil.copy2(_BRIDGE_SRC, scripts_dir / "flux_bridge.py")
    except Exception as exc:
        return {"success": False, "message": f"Failed to deploy flux_bridge.py: {exc}", "path": None}

    _NEW_BLOCK = (
        f"{_BLOCK_BEGIN}\n"
        f"try:\n"
        f"    import sys as _s, os as _o\n"
        f"    _s.path.insert(0, _o.path.dirname(_o.path.abspath(__file__)))\n"
        f"    import flux_bridge\n"
        f"except Exception as _e:\n"
        f"    print(f'[FLUX] Autostart error (Maya continues normally): {{_e}}')\n"
        f"{_BLOCK_END}"
    )

    existing = startup.read_text(encoding="utf-8") if startup.exists() else ""

    if _BLOCK_BEGIN in existing:
        b_start = existing.find(_BLOCK_BEGIN)
        b_end   = existing.find(_BLOCK_END, b_start)
        old_fragment = existing[b_start : b_end + len(_BLOCK_END)] if b_end > b_start else ""
        needs_upgrade = "try:" not in old_fragment or "flux_bridge" not in old_fragment
        if needs_upgrade:
            try:
                startup.write_text(existing.replace(old_fragment, _NEW_BLOCK), encoding="utf-8")
            except OSError as exc:
                return {"success": False, "message": f"Cannot upgrade userSetup.py: {exc}", "path": str(startup)}
            return {"success": True, "message": f"upgraded: {startup}", "path": str(startup)}
        return {"success": True, "message": "already_installed", "path": str(startup)}

    block = f"\n{_NEW_BLOCK}\n"
    try:
        with open(startup, "a", encoding="utf-8") as fh:
            fh.write(block)
    except OSError as exc:
        return {"success": False, "message": f"Cannot write userSetup.py: {exc}", "path": str(startup)}

    return {"success": True, "message": f"installed: {startup}", "path": str(startup)}


def uninstall(maya_exe_path: str | None = None) -> dict:
    """Remove the FLUX autostart block from userSetup.py.

    Returns {"success": bool, "message": str}
    """
    startup = get_startup_file(maya_exe_path)
    if startup is None or not startup.exists():
        return {"success": True, "message": "not_installed"}

    try:
        content = startup.read_text(encoding="utf-8")
    except OSError as exc:
        return {"success": False, "message": f"Cannot read userSetup.py: {exc}"}

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
        return {"success": False, "message": f"Cannot write userSetup.py: {exc}"}

    return {"success": True, "message": "uninstalled"}

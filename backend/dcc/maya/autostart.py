# autostart.py — FLUX Maya userSetup.py manager.
# Installs / removes the FLUX autostart block in every Maya version's userSetup.py.
#
# Path resolution strategy (no hardcoding):
#   1. Locate MAYA_APP_DIR:
#        - $MAYA_APP_DIR env var (explicit override)
#        - Windows : winreg Personal → Documents/maya
#        - macOS   : ~/Library/Preferences/Autodesk/maya
#        - Linux   : ~/maya
#   2. Glob MAYA_APP_DIR/20*/scripts/userSetup.py  (all installed versions)
#      + MAYA_APP_DIR/scripts/userSetup.py          (version-agnostic, loaded by all versions)
#   3. Install/remove the FLUX block in EVERY discovered file.
#
# This mirrors the pattern used by tools like hconfig (Houdini) that query the filesystem
# rather than hardcode paths — works on any machine regardless of Maya version.

from __future__ import annotations

import os
import platform
import re
from pathlib import Path

# ── Block markers — never change, they identify the FLUX block ────────────────
_BLOCK_BEGIN = "# >>> FLUX autostart — do not edit manually"
_BLOCK_END   = "# <<< FLUX autostart"


# ── MAYA_APP_DIR resolution ───────────────────────────────────────────────────

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


def _get_maya_app_dir() -> Path | None:
    """Locate MAYA_APP_DIR using env var → OS default, without running Maya.

    Equivalent to what `hconfig -j` does for Houdini.
    Returns None if no maya prefs directory is found.
    """
    # Explicit override — highest priority
    env = os.environ.get("MAYA_APP_DIR", "").strip()
    if env:
        candidate = Path(env)
        if candidate.exists():
            return candidate

    system = platform.system()
    if system == "Windows":
        base = _get_documents_dir() / "maya"
    elif system == "Darwin":
        base = Path.home() / "Library" / "Preferences" / "Autodesk" / "maya"
    else:
        base = Path.home() / "maya"

    return base if base.exists() else None


def _discover_startup_files(maya_app_dir: Path) -> list[Path]:
    """Return every userSetup.py path that Maya may execute on startup.

    Includes:
    - maya_app_dir/20*/scripts/userSetup.py  (one per installed version)
    - maya_app_dir/scripts/userSetup.py      (version-agnostic, loaded by all)

    Files do not need to exist yet — the list defines where we WILL write.
    Missing parent directories are created by install().
    """
    targets: list[Path] = []

    # All version-specific folders (e.g. 2022, 2024, 2026, ...)
    try:
        for ver_dir in sorted(maya_app_dir.glob("20*"), key=lambda d: d.name):
            if ver_dir.is_dir():
                targets.append(ver_dir / "scripts" / "userSetup.py")
    except OSError:
        pass

    # Version-agnostic fallback (loaded by all versions as part of MAYA_SCRIPT_PATH)
    targets.append(maya_app_dir / "scripts" / "userSetup.py")

    return targets


# ── Public API ────────────────────────────────────────────────────────────────

def get_startup_file(maya_exe_path: str | None = None) -> Path | None:
    """Return the primary userSetup.py path for display / status checks.

    For backwards compatibility with the router (which expects a single path).
    Returns the most-recently-modified version-specific file, or the version-agnostic
    one as a fallback.
    """
    app_dir = _get_maya_app_dir()
    if app_dir is None:
        return None

    # Prefer the most recent version folder that has a scripts/ directory
    try:
        ver_dirs = sorted(
            [d for d in app_dir.glob("20*") if d.is_dir()],
            key=lambda d: d.name, reverse=True,
        )
        for vd in ver_dirs:
            scripts = vd / "scripts"
            if scripts.is_dir():
                return scripts / "userSetup.py"
    except OSError:
        pass

    return app_dir / "scripts" / "userSetup.py"


def is_installed(maya_exe_path: str | None = None) -> bool:
    """Return True when at least one discovered userSetup.py has a valid FLUX block.

    A valid block must contain the direct commandPort call (not the old flux_bridge pattern).
    """
    app_dir = _get_maya_app_dir()
    if app_dir is None:
        return False

    for path in _discover_startup_files(app_dir):
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _BLOCK_BEGIN not in content:
            continue
        b_start = content.find(_BLOCK_BEGIN)
        b_end   = content.find(_BLOCK_END, b_start)
        fragment = content[b_start : b_end + len(_BLOCK_END)] if b_end > b_start else ""
        if "commandPort" in fragment:
            return True

    return False


def install(maya_exe_path: str | None = None) -> dict:
    """Write the FLUX autostart block into every Maya version's userSetup.py.

    The block:
      1. Adds the Flux backend dir to sys.path (synchronously — no Maya cmds needed).
      2. Opens commandPort via executeDeferred so Maya is fully initialised first.
         Uses commandPort(query=True) to avoid double-bind on repeated startups.

    Idempotent — always writes the latest block, replacing any stale version.
    Works for any Maya version found on the machine; no paths are hardcoded.
    Returns {"success": bool, "message": str, "path": str | None}
    """
    app_dir = _get_maya_app_dir()
    if app_dir is None:
        return {"success": False, "message": "Maya prefs directory not found, launch Maya once to create it", "path": None}

    # Flux backend directory resolved at runtime (no hardcoding).
    _flux_backend = str(Path(__file__).resolve().parent.parent.parent)

    # Port resolved from constants — reinstalling picks up any change automatically.
    try:
        from core.constants import DCC_PORTS
        _maya_port = DCC_PORTS.get("Maya", 7001)
    except ImportError:
        _maya_port = 7001

    _NEW_BLOCK = (
        f"{_BLOCK_BEGIN}\n"
        f"try:\n"
        f"    import sys as _s, maya.utils as _mu\n"
        f"    if r'{_flux_backend}' not in _s.path:\n"
        f"        _s.path.insert(0, r'{_flux_backend}')\n"
        f"    def _flux_open_port():\n"
        f"        try:\n"
        f"            import maya.cmds as _c\n"
        f"            _p = ':{_maya_port}'\n"
        f"            if not _c.commandPort(_p, query=True):\n"
        f"                _c.commandPort(name=_p, sourceType='python', noreturn=False)\n"
        f"            print('[FLUX] commandPort {_maya_port} opened')\n"
        f"        except Exception as _e:\n"
        f"            print(f'[FLUX] commandPort error: {{_e}}')\n"
        f"    _mu.executeDeferred(_flux_open_port)\n"
        f"except Exception as _e:\n"
        f"    print(f'[FLUX] autostart error: {{_e}}')\n"
        f"{_BLOCK_END}"
    )

    targets = _discover_startup_files(app_dir)
    written: list[str] = []
    errors:  list[str] = []

    for startup in targets:
        startup.parent.mkdir(parents=True, exist_ok=True)

        existing = ""
        if startup.exists():
            try:
                existing = startup.read_text(encoding="utf-8")
            except OSError as exc:
                errors.append(f"{startup.name}: read error: {exc}")
                continue

        if _BLOCK_BEGIN in existing:
            b_start = existing.find(_BLOCK_BEGIN)
            b_end   = existing.find(_BLOCK_END, b_start)
            old_frag = existing[b_start : b_end + len(_BLOCK_END)] if b_end > b_start else ""
            if old_frag == _NEW_BLOCK:
                continue  # already up to date
            try:
                startup.write_text(existing.replace(old_frag, _NEW_BLOCK), encoding="utf-8")
                written.append(str(startup))
            except OSError as exc:
                errors.append(f"{startup.name}: write error: {exc}")
        else:
            try:
                with open(startup, "a", encoding="utf-8") as fh:
                    fh.write(f"\n{_NEW_BLOCK}\n")
                written.append(str(startup))
            except OSError as exc:
                errors.append(f"{startup.name}: write error: {exc}")

    if errors and not written:
        return {"success": False, "message": "; ".join(errors), "path": None}

    primary = get_startup_file(maya_exe_path)
    msg = f"installed in {len(written)} file(s)" if written else "already_installed"
    return {"success": True, "message": msg, "path": str(primary) if primary else None}


def uninstall(maya_exe_path: str | None = None) -> dict:
    """Remove the FLUX autostart block from every Maya version's userSetup.py.

    Returns {"success": bool, "message": str}
    """
    app_dir = _get_maya_app_dir()
    if app_dir is None:
        return {"success": True, "message": "not_installed"}

    removed = 0
    for path in _discover_startup_files(app_dir):
        if not path.exists():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if _BLOCK_BEGIN not in content:
            continue
        cleaned = re.sub(
            rf"\n?{re.escape(_BLOCK_BEGIN)}.*?{re.escape(_BLOCK_END)}\n?",
            "",
            content,
            flags=re.DOTALL,
        )
        try:
            path.write_text(cleaned, encoding="utf-8")
            removed += 1
        except OSError:
            pass

    if removed == 0:
        return {"success": True, "message": "not_installed"}
    return {"success": True, "message": f"uninstalled from {removed} file(s)"}

# shelf_core.py — install/remove/update Flux shelves in DCC user directories.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)


# ── Windows Documents folder (handles OneDrive / school redirects) ────────────

def _get_documents_dir() -> Path:
    """Return the user's actual Documents folder via Windows registry.

    Falls back to ~/Documents when the registry key is unavailable (non-Windows).
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        )
        docs, _ = winreg.QueryValueEx(key, "Personal")
        winreg.CloseKey(key)
        return Path(docs)
    except Exception:
        return Path.home() / "Documents"


# ── Shelf filenames per DCC ───────────────────────────────────────────────────
_SHELF_FILENAME: dict[str, str] = {
    "Maya":    "shelf_Flux.mel",
    "Houdini": "Flux.shelf",
}

# Resources root resolved at import time (package root / resources / shelves)
_RESOURCES_ROOT: Path = (
    Path(__file__).parent.parent.parent.parent / "resources" / "shelves"
)


# ── public API ────────────────────────────────────────────────────────────────

def get_shelf_source_path(dcc_name: str) -> Path | None:
    """Return the bundled shelf source file path, or None if DCC is unsupported."""
    filename = _SHELF_FILENAME.get(dcc_name)
    if filename is None:
        return None
    return _RESOURCES_ROOT / dcc_name.lower() / filename


def get_dcc_shelf_dir(dcc_name: str, version: str) -> Path | None:
    """Return the user shelf directory for a given DCC version, or None if unsupported.

    Respects MAYA_APP_DIR / HOUDINI_USER_PREF_DIR env vars when set.
    Falls back to the actual Documents folder (registry-resolved on Windows).
    """
    docs = _get_documents_dir()
    if dcc_name == "Maya":
        base = Path(os.environ["MAYA_APP_DIR"]) if "MAYA_APP_DIR" in os.environ else docs / "maya"
        return base / version / "prefs" / "shelves"
    if dcc_name == "Houdini":
        if "HOUDINI_USER_PREF_DIR" in os.environ:
            return Path(os.environ["HOUDINI_USER_PREF_DIR"]) / "toolbar"
        return docs / f"houdini{version}" / "toolbar"
    return None


def get_installed_versions(dcc_name: str) -> list[str]:
    """Return sorted list of DCC user-directory versions found on disk.

    Checks MAYA_APP_DIR / HOUDINI_USER_PREF_DIR first, then the registry-resolved
    Documents folder. Only directories whose names start with a digit are included.
    """
    docs = _get_documents_dir()
    versions: list[str] = []

    if dcc_name == "Maya":
        base = Path(os.environ["MAYA_APP_DIR"]) if "MAYA_APP_DIR" in os.environ else docs / "maya"
        if base.is_dir():
            versions = [
                d.name for d in sorted(base.iterdir())
                if d.is_dir() and d.name[:1].isdigit()
            ]

    elif dcc_name == "Houdini":
        if docs.is_dir():
            for d in sorted(docs.iterdir()):
                if d.is_dir() and d.name.lower().startswith("houdini"):
                    suffix = d.name[len("houdini"):]
                    if suffix[:1].isdigit():
                        versions.append(suffix)

    return versions


def is_shelf_installed(dcc_name: str, version: str) -> bool:
    """Return True if the Flux shelf file exists in the DCC user directory."""
    shelf_dir = get_dcc_shelf_dir(dcc_name, version)
    filename = _SHELF_FILENAME.get(dcc_name)
    if shelf_dir is None or filename is None:
        return False
    return (shelf_dir / filename).is_file()


def install_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Copy the bundled shelf file to the DCC user directory.

    Returns (success, message).
    """
    src = get_shelf_source_path(dcc_name)
    if src is None:
        return False, f"DCC '{dcc_name}' is not supported."
    if not src.is_file():
        return False, f"Source shelf not found: {src}"

    dest_dir = get_dcc_shelf_dir(dcc_name, version)
    if dest_dir is None:
        return False, f"Cannot resolve shelf directory for {dcc_name} {version}."

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        shutil.copy2(src, dest)
        log.info("Shelf installed: %s → %s", src.name, dest)
        return True, f"Installed → {dest}"
    except OSError as exc:
        log.error("Shelf install failed: %s", exc)
        return False, f"Error: {exc}"


def remove_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Remove the Flux shelf file from the DCC user directory.

    Returns (success, message).
    """
    dest_dir = get_dcc_shelf_dir(dcc_name, version)
    filename = _SHELF_FILENAME.get(dcc_name)
    if dest_dir is None or filename is None:
        return False, f"Cannot resolve shelf directory for {dcc_name} {version}."

    target = dest_dir / filename
    if not target.is_file():
        return False, f"Shelf not installed: {target}"

    try:
        target.unlink()
        log.info("Shelf removed: %s", target)
        return True, f"Removed: {target}"
    except OSError as exc:
        log.error("Shelf removal failed: %s", exc)
        return False, f"Error: {exc}"


def update_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Remove then reinstall the shelf. Returns (success, message)."""
    if is_shelf_installed(dcc_name, version):
        ok, msg = remove_shelf(dcc_name, version)
        if not ok:
            return False, f"Update aborted — remove failed: {msg}"
    return install_shelf(dcc_name, version)


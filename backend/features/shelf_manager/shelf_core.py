# shelf_core.py — install/remove/update Flux shelves in DCC user directories.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

# Staging dir — HDAs are copied here at first launch, then to houdiniX.Y/otls/ on shelf install.
_HDA_STAGING_DIR: Path = (
    Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming"))
    / "FLUX" / "dcc" / "houdini"
)


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
    Path(__file__).parent.parent.parent / "resources" / "shelves"
)


# ── Maya installation shelf dir ───────────────────────────────────────────────

def _get_maya_install_shelf_dir(version: str) -> Path | None:
    """Return the global Maya installation shelf dir for a given version.

    Checks MAYA_LOCATION env var first, then standard install paths on Windows.
    Returns None if the directory does not exist (Maya not installed or non-standard path).
    """
    candidates: list[Path] = []

    if "MAYA_LOCATION" in os.environ:
        candidates.append(Path(os.environ["MAYA_LOCATION"]) / "scripts" / "shelves")

    # Standard Windows install paths
    for root in (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Autodesk",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Autodesk",
    ):
        candidates.append(root / f"Maya{version}" / "scripts" / "shelves")

    for p in candidates:
        if p.is_dir():
            return p
    return None


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

    For Houdini, also installs HDAs into houdiniX.Y/otls/ (non-fatal if it fails).
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
    except OSError as exc:
        log.error("Shelf install failed: %s", exc)
        return False, f"Error: {exc}"

    if dcc_name == "Maya":
        install_dir = _get_maya_install_shelf_dir(version)
        if install_dir is not None:
            try:
                shutil.copy2(src, install_dir / src.name)
                log.info("Shelf also installed to Maya dir: %s", install_dir)
            except OSError as exc:
                log.warning("Could not install shelf to Maya dir (non-fatal): %s", exc)

    if dcc_name == "Houdini":
        ok_hda, msg_hda = install_hdas(version)
        if not ok_hda:
            log.warning("HDA install failed (non-fatal): %s", msg_hda)

    return True, f"Installed → {dest}"


# ── Maya tools catalog (choisir quel tool installer) ──────────────────────────
# Chaque tool = un shelf Maya autonome (1 bouton) dans resources/shelves/maya/.
MAYA_TOOLS: list[dict] = [
    {"id": "flux",      "label": "Flux Pipeline",        "filename": "shelf_Flux.mel"},
    {"id": "adam_rig",   "label": "Flux Rigging Tool",    "filename": "shelf_AntRigToolbox.mel"},
    {"id": "flux_anim", "label": "Flux Animation Tool",  "filename": "shelf_FluxAnimTool.mel"},
]


def _tool(tool_id: str) -> dict | None:
    return next((t for t in MAYA_TOOLS if t["id"] == tool_id), None)


def list_tools() -> list[dict]:
    """Catalogue des tools Maya installables (id + label + fichier)."""
    return [dict(t) for t in MAYA_TOOLS]


def is_tool_installed(tool_id: str, version: str) -> bool:
    t = _tool(tool_id)
    shelf_dir = get_dcc_shelf_dir("Maya", version)
    if not t or shelf_dir is None:
        return False
    return (shelf_dir / t["filename"]).is_file()


def install_tool_shelf(tool_id: str, version: str) -> tuple[bool, str]:
    """Copie le shelf d'un tool du catalogue dans le dossier shelves de Maya."""
    t = _tool(tool_id)
    if not t:
        return False, f"Tool inconnu : '{tool_id}'."
    src = _RESOURCES_ROOT / "maya" / t["filename"]
    if not src.is_file():
        return False, f"Source shelf introuvable : {src}"
    dest_dir = get_dcc_shelf_dir("Maya", version)
    if dest_dir is None:
        return False, f"Dossier shelves Maya {version} introuvable."
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest_dir / src.name)
    except OSError as exc:
        return False, f"Erreur : {exc}"
    install_dir = _get_maya_install_shelf_dir(version)
    if install_dir is not None:
        try:
            shutil.copy2(src, install_dir / src.name)
        except OSError:
            pass
    return True, f"Installé → {dest_dir / src.name}"


def remove_tool_shelf(tool_id: str, version: str) -> tuple[bool, str]:
    """Retire le shelf d'un tool du catalogue."""
    t = _tool(tool_id)
    if not t:
        return False, f"Tool inconnu : '{tool_id}'."
    removed = False
    for d in (get_dcc_shelf_dir("Maya", version),
              _get_maya_install_shelf_dir(version)):
        if d is None:
            continue
        f = d / t["filename"]
        try:
            if f.is_file():
                f.unlink()
                removed = True
        except OSError as exc:
            return False, f"Erreur : {exc}"
    return (removed, "Retiré" if removed else "Rien à retirer")


def remove_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Remove the Flux shelf file from the DCC user directory.

    For Houdini, also removes HDAs from houdiniX.Y/otls/ (non-fatal if it fails).
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
    except OSError as exc:
        log.error("Shelf removal failed: %s", exc)
        return False, f"Error: {exc}"

    if dcc_name == "Maya":
        install_dir = _get_maya_install_shelf_dir(version)
        if install_dir is not None:
            install_copy = install_dir / filename
            if install_copy.is_file():
                try:
                    install_copy.unlink()
                    log.info("Shelf removed from Maya dir: %s", install_copy)
                except OSError as exc:
                    log.warning("Could not remove shelf from Maya dir (non-fatal): %s", exc)

    if dcc_name == "Houdini":
        ok_hda, msg_hda = remove_hdas(version)
        if not ok_hda:
            log.warning("HDA removal failed (non-fatal): %s", msg_hda)

    return True, f"Removed: {target}"


def update_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Remove then reinstall the shelf. Returns (success, message)."""
    if is_shelf_installed(dcc_name, version):
        ok, msg = remove_shelf(dcc_name, version)
        if not ok:
            return False, f"Update aborted, remove failed: {msg}"
    return install_shelf(dcc_name, version)


# ── Houdini HDA management ────────────────────────────────────────────────────

def get_dcc_otls_dir(version: str) -> Path | None:
    """Return Documents/houdiniX.Y/otls/, creating it if needed.

    Respects HOUDINI_USER_PREF_DIR when set.
    """
    if "HOUDINI_USER_PREF_DIR" in os.environ:
        return Path(os.environ["HOUDINI_USER_PREF_DIR"]) / "otls"
    docs = _get_documents_dir()
    if not docs.is_dir():
        return None
    return docs / f"houdini{version}" / "otls"


def is_hda_installed(version: str) -> bool:
    """Return True if all FLUX HDAs are present in houdiniX.Y/otls/."""
    otls = get_dcc_otls_dir(version)
    if otls is None:
        return False
    staged = list(_HDA_STAGING_DIR.glob("*.hda"))
    if not staged:
        return False
    return all((otls / hda.name).is_file() for hda in staged)


def install_hdas(version: str) -> tuple[bool, str]:
    """Copy FLUX HDAs from staging dir to houdiniX.Y/otls/.

    Primary path: offline copy from %APPDATA%/FLUX/dcc/houdini/ (populated at first launch).
    Fallback: live build via houdini_client (requires Houdini connected).
    Returns (success, message).
    """
    hdas = list(_HDA_STAGING_DIR.glob("*.hda"))
    otls = get_dcc_otls_dir(version)

    if hdas and otls is not None:
        try:
            otls.mkdir(parents=True, exist_ok=True)
            for hda in hdas:
                shutil.copy2(hda, otls / hda.name)
                log.info("HDA installed: %s → %s", hda.name, otls)
            return True, f"HDAs installed → {otls}"
        except OSError as exc:
            return False, f"HDA copy failed: {exc}"

    # Live fallback — requires Houdini connected (import inside body to avoid circular deps)
    if otls is not None:
        try:
            from dcc.houdini.hda.flux_importer_hda import build_hda as build_importer
            from dcc.houdini.hda.flux_exporter_hda import build_hda as build_exporter
        except ImportError as exc:
            return False, f"Cannot import HDA builders: {exc}"

        try:
            otls.mkdir(parents=True, exist_ok=True)
            r = build_importer(str(otls / "flux_importer.hda"))
            if not r.get("ok"):
                return False, f"Live build (importer) failed: {r.get('error')}"
            r = build_exporter(str(otls / "flux_exporter.hda"))
            if not r.get("ok"):
                return False, f"Live build (exporter) failed: {r.get('error')}"
            return True, f"HDAs built live → {otls}"
        except Exception as exc:
            return False, f"Live build error: {exc}"

    if not hdas:
        return False, "No staged HDAs found. Run the installer first or build via scripts/build_hdas.py."
    return False, f"Cannot resolve otls directory for Houdini {version}."


def remove_hdas(version: str) -> tuple[bool, str]:
    """Remove FLUX HDAs from houdiniX.Y/otls/. Returns (success, message)."""
    otls = get_dcc_otls_dir(version)
    if otls is None:
        return False, f"Cannot resolve otls directory for Houdini {version}."

    staged = list(_HDA_STAGING_DIR.glob("*.hda"))
    if not staged:
        return True, "No HDAs to remove."

    removed: list[str] = []
    errors: list[str] = []
    for hda in staged:
        target = otls / hda.name
        if target.is_file():
            try:
                target.unlink()
                removed.append(hda.name)
                log.info("HDA removed: %s", target)
            except OSError as exc:
                errors.append(f"{hda.name}: {exc}")

    if errors:
        return False, f"Partial removal, errors: {'; '.join(errors)}"
    if not removed:
        return True, "HDAs were not installed."
    return True, f"Removed: {', '.join(removed)}"


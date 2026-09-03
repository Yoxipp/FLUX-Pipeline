# shelf_core.py — install/remove/update Flux shelves in DCC user directories.

from __future__ import annotations

import os
import shutil
from pathlib import Path

from core import config
from core.logger import get_logger

log = get_logger(__name__)

# Persisted selection of Maya shelf tools (survives uninstall/reinstall)
_SHELF_TOOLS_KEY = "maya_shelf_tools"

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

    For Maya, builds a single Flux shelf from the persisted tool selection.
    For Houdini, also installs HDAs into houdiniX.Y/otls/ (non-fatal if it fails).
    Returns (success, message).
    """
    if dcc_name == "Maya":
        return install_flux_shelf(version)

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

    # NOTE: the Houdini importer/exporter HDAs are a technical dependency, not a
    # shelf tool — they are installed by the Houdini autostart connection
    # (dcc.houdini.autostart.install), so they are NOT installed here.

    return True, f"Installed → {dest}"


# ── Maya tools → single Flux shelf ────────────────────────────────────────────
# ONE Flux shelf (shelf_Flux.mel) is generated from the SELECTED tools' buttons:
# each tool source .mel contributes the shelfButtons inside its `global proc`.
# Only two user-facing tools ship on the Flux shelf: ANIM (animation) and RIG
# (rigging toolbox). Order matches the shelf layout [ ANIM ] [ RIG ]. The old
# "flux" pipeline button is not a shelf tool; the Houdini importer HDA is a
# technical dependency installed via the Houdini autostart, not from the shelf.
MAYA_TOOLS: list[dict] = [
    {"id": "flux_anim", "label": "ANIM", "filename": "shelf_FluxAnimTool.mel"},
    {"id": "adam_rig",   "label": "RIG",  "filename": "shelf_AntRigToolbox.mel"},
]


def _tool(tool_id: str) -> dict | None:
    return next((t for t in MAYA_TOOLS if t["id"] == tool_id), None)


def list_tools() -> list[dict]:
    """Catalogue des tools Maya (id + label + fichier)."""
    return [dict(t) for t in MAYA_TOOLS]


def get_shelf_tool_selection() -> list[str]:
    """Return the persisted tool selection (defaults to all tools)."""
    sel = config.get(_SHELF_TOOLS_KEY)
    if isinstance(sel, list):
        return [s for s in sel if _tool(s)]   # may be empty if all unchecked
    return [t["id"] for t in MAYA_TOOLS]


def set_shelf_tool_selection(ids: list[str]) -> None:
    config.set(_SHELF_TOOLS_KEY, [i for i in ids if _tool(i)])


def is_shelf_tool_active(tool_id: str, version: str) -> bool:
    """A tool is 'active' when it's selected AND the Flux shelf is installed."""
    return tool_id in get_shelf_tool_selection() and is_shelf_installed("Maya", version)


def _extract_shelf_body(mel_text: str) -> str:
    """Return the shelfButton block between the proc's first '{' and last '}'."""
    start = mel_text.find("{")
    end = mel_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return ""
    return mel_text[start + 1:end].strip("\n")


def build_flux_shelf_mel(selected_ids: list[str]) -> str:
    """Compose a single shelf_Flux.mel from the selected tools' buttons."""
    bodies: list[str] = []
    for tid in selected_ids:
        t = _tool(tid)
        if not t:
            continue
        src = _RESOURCES_ROOT / "maya" / t["filename"]
        if not src.is_file():
            log.warning("Shelf tool source missing: %s", src)
            continue
        body = _extract_shelf_body(src.read_text(encoding="utf-8"))
        if body:
            bodies.append(f"    // ── {t['label']} ──\n{body}")
    inner = "\n".join(bodies)
    return (
        "// shelf_Flux.mel — generated by the Flux Shelf Manager.\n"
        "// Single Flux shelf containing the selected tools.\n\n"
        "global proc shelf_Flux() {\n"
        f"{inner}\n"
        "}\n"
    )


def _deploy_maya_icons(version: str) -> None:
    """Copy the Flux shelf icons into Maya's prefs/icons dir (on XBMLANGPATH).

    Maya resolves a shelfButton's -image1 by filename against XBMLANGPATH, which
    includes ``<maya>/<version>/prefs/icons``. Copying the bundled PNGs there lets
    the ANIM (orange) / RIG (blue) FLUX icons show without absolute paths. Best-effort.
    """
    shelf_dir = get_dcc_shelf_dir("Maya", version)
    if shelf_dir is None:
        return
    icons_src = _RESOURCES_ROOT / "maya" / "icons"
    if not icons_src.is_dir():
        return
    icons_dst = shelf_dir.parent / "icons"
    try:
        icons_dst.mkdir(parents=True, exist_ok=True)
        for png in icons_src.glob("*.png"):
            shutil.copy2(png, icons_dst / png.name)
    except OSError as exc:
        log.warning("Could not deploy Maya shelf icons (non-fatal): %s", exc)


def install_flux_shelf(version: str, selected_ids: list[str] | None = None) -> tuple[bool, str]:
    """Generate + install the single Flux shelf from the given (or persisted) tools.

    Persists the selection so a later uninstall/reinstall keeps the same choices.
    """
    ids = selected_ids if selected_ids is not None else get_shelf_tool_selection()
    set_shelf_tool_selection(ids)

    dest_dir = get_dcc_shelf_dir("Maya", version)
    if dest_dir is None:
        return False, f"Dossier shelves Maya {version} introuvable."

    mel = build_flux_shelf_mel(ids)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / "shelf_Flux.mel").write_text(mel, encoding="utf-8")
    except OSError as exc:
        return False, f"Erreur : {exc}"

    _deploy_maya_icons(version)

    install_dir = _get_maya_install_shelf_dir(version)
    if install_dir is not None:
        try:
            (install_dir / "shelf_Flux.mel").write_text(mel, encoding="utf-8")
        except OSError:
            pass

    n = len([i for i in ids if _tool(i)])
    return True, f"Shelf Flux installé ({n} tool(s)) → {dest_dir / 'shelf_Flux.mel'}"


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

    # Houdini HDAs are removed by the autostart uninstall (they are a pipeline
    # dependency, not a shelf tool), so they are NOT removed here.

    return True, f"Removed: {target}"


def update_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Remove then reinstall the shelf. Returns (success, message)."""
    if is_shelf_installed(dcc_name, version):
        ok, msg = remove_shelf(dcc_name, version)
        if not ok:
            return False, f"Update aborted, remove failed: {msg}"
    return install_shelf(dcc_name, version)


# ── Houdini HDA management ────────────────────────────────────────────────────

def get_dcc_otls_dirs(version: str) -> list[Path]:
    """Return every otls dir Houdini might scan for HDAs, for THIS version.

    On Windows, Houdini's user prefs live under either the home directory
    (``~/houdiniX.Y``) or a registry/OneDrive-redirected Documents folder, and
    which one is active varies per machine. The autostart already writes to both
    (``autostart._all_prefs_dirs``); the HDA install must match, otherwise it lands
    in the wrong root and ``flux_importer`` never registers ("Invalid node type name" /
    "HDA non installée"). We return the otls dir under every candidate prefs root whose
    ``houdiniX.Y`` directory exists, so the HDA is installed wherever Houdini reads it.

    Honors HOUDINI_USER_PREF_DIR when set (single authoritative root).
    """
    if "HOUDINI_USER_PREF_DIR" in os.environ:
        return [Path(os.environ["HOUDINI_USER_PREF_DIR"]) / "otls"]

    dirs: list[Path] = []
    home = Path.home()
    docs = _get_documents_dir()
    for base in (home, docs):   # home first: the plain ~/houdiniX.Y is Houdini's default
        prefs = base / f"houdini{version}"
        otls = prefs / "otls"
        if prefs.is_dir() and otls not in dirs:
            dirs.append(otls)
    return dirs


def get_dcc_otls_dir(version: str) -> Path | None:
    """Primary otls dir for *version* (first candidate), or None if no prefs dir exists.

    Kept for callers that need a single path; install/remove operate on all roots
    via get_dcc_otls_dirs().
    """
    dirs = get_dcc_otls_dirs(version)
    return dirs[0] if dirs else None


def is_hda_installed(version: str) -> bool:
    """Return True if all FLUX HDAs are present in at least one houdiniX.Y/otls/."""
    otls_dirs = get_dcc_otls_dirs(version)
    if not otls_dirs:
        return False
    staged = list(_HDA_STAGING_DIR.glob("*.hda"))
    if not staged:
        return False
    return any(
        all((otls / hda.name).is_file() for hda in staged)
        for otls in otls_dirs
    )


def _build_hdas_live(otls_dirs: list[Path]) -> tuple[bool, str]:
    """Build the FLUX HDAs in the connected Houdini into otls_dirs[0], mirror the
    resulting .hda files into the other otls dirs AND refresh the staging copy.

    A live build regenerates the HDA from source, so any fix to the builders
    (e.g. the importer format_switch expression) propagates here — unlike a plain
    copy of a possibly-stale staged .hda. Requires Houdini connected.
    """
    try:
        from dcc.houdini.hda.flux_importer_hda import build_hda as build_importer
        from dcc.houdini.hda.flux_exporter_hda import build_hda as build_exporter
        from dcc.houdini.hda.flux_lighting_hda import build_hda as build_lighting
    except ImportError as exc:
        return False, f"Cannot import HDA builders: {exc}"

    try:
        otls = otls_dirs[0]
        otls.mkdir(parents=True, exist_ok=True)
        r = build_importer(str(otls / "flux_importer.hda"))
        if not r.get("ok"):
            return False, f"Live build (importer) failed: {r.get('error')}"
        r = build_exporter(str(otls / "flux_exporter.hda"))
        if not r.get("ok"):
            return False, f"Live build (exporter) failed: {r.get('error')}"
        r = build_lighting(str(otls / "flux_lighting.hda"))
        if not r.get("ok"):
            return False, f"Live build (lighting) failed: {r.get('error')}"

        built_names = ("flux_importer.hda", "flux_exporter.hda", "flux_lighting.hda")
        # Mirror into the other otls roots so Houdini finds it wherever it reads.
        for other in otls_dirs[1:]:
            try:
                other.mkdir(parents=True, exist_ok=True)
                for built in built_names:
                    shutil.copy2(otls / built, other / built)
            except OSError as exc:
                log.warning("Could not mirror live-built HDA to %s: %s", other, exc)
        # Refresh the offline staging copy so later offline installs use the fix too.
        try:
            _HDA_STAGING_DIR.mkdir(parents=True, exist_ok=True)
            for built in built_names:
                shutil.copy2(otls / built, _HDA_STAGING_DIR / built)
        except OSError as exc:
            log.warning("Could not refresh HDA staging copy: %s", exc)
        return True, f"HDAs built live → {otls}"
    except Exception as exc:
        return False, f"Live build error: {exc}"


def install_hdas(version: str) -> tuple[bool, str]:
    """Install the FLUX HDAs into EVERY houdiniX.Y/otls/ Houdini may read.

    When Houdini is connected, the HDAs are BUILT LIVE from source so builder fixes
    propagate (idempotent — same filenames, no duplicates). When Houdini is offline,
    fall back to copying the staged .hda from %APPDATA%/FLUX/dcc/houdini/.
    Returns (success, message).
    """
    otls_dirs = get_dcc_otls_dirs(version)
    if not otls_dirs:
        return False, f"Cannot resolve otls directory for Houdini {version}."

    # Prefer a fresh live build when Houdini is reachable.
    try:
        from dcc.houdini.client import houdini_client
        connected = houdini_client.is_connected()
    except Exception:
        connected = False

    if connected:
        ok, msg = _build_hdas_live(otls_dirs)
        if ok:
            return ok, msg
        log.warning("Live HDA build failed, falling back to staged copy: %s", msg)

    # Offline path — copy the staged HDAs.
    hdas = list(_HDA_STAGING_DIR.glob("*.hda"))
    if hdas:
        installed_to: list[str] = []
        try:
            for otls in otls_dirs:
                otls.mkdir(parents=True, exist_ok=True)
                for hda in hdas:
                    shutil.copy2(hda, otls / hda.name)
                    log.info("HDA installed: %s → %s", hda.name, otls)
                installed_to.append(str(otls))
            return True, f"HDAs installed → {', '.join(installed_to)}"
        except OSError as exc:
            return False, f"HDA copy failed: {exc}"

    return False, (
        "No staged HDAs found and Houdini is not connected. Open Houdini (so the "
        "HDA can be built live) or run scripts/build_hdas.py, then retry."
    )


def reconcile_installed_dccs() -> dict:
    """Refresh already-installed FLUX shelves/HDAs when the bundled copy is newer.

    Run at every FLUX launch (see main.lifespan). The rule is deliberately narrow:
    only touch a DCC version that ALREADY has FLUX installed — never install where
    the user never opted in — and only overwrite when the shipped content is newer.

    Maya  : the Flux shelf is regenerated from the current tool catalogue; if its
            content drifted from the installed shelf_Flux.mel (e.g. FLUX now ships
            only ANIM + RIG), the shelf is rewritten so the next Maya launch is current.
    Houdini: each FLUX .hda already present in a houdiniX.Y/otls/ is replaced by the
            freshly-staged copy when the staged file is newer. This is what carries
            the importer's format_switch fix onto machines that still have a stale
            (crashing) flux_importer.hda from an older FLUX build.

    Idempotent and best-effort — a failure never blocks startup.
    Returns {"maya": [...], "houdini": [...]} describing what was updated.
    """
    report: dict = {"maya": [], "houdini": []}

    # ── Maya: rewrite a drifted Flux shelf ────────────────────────────────────
    for version in get_installed_versions("Maya"):
        if not is_shelf_installed("Maya", version):
            continue
        dest_dir = get_dcc_shelf_dir("Maya", version)
        if dest_dir is None:
            continue
        want = build_flux_shelf_mel(get_shelf_tool_selection())
        try:
            have = (dest_dir / "shelf_Flux.mel").read_text(encoding="utf-8")
        except OSError:
            have = ""
        if have != want:
            ok, msg = install_flux_shelf(version)
            log.info("Auto-update Maya %s shelf: %s", version, msg)
            report["maya"].append({"version": version, "ok": ok, "msg": msg})

    # ── Houdini: replace stale HDAs already present in otls/ ───────────────────
    staged = list(_HDA_STAGING_DIR.glob("*.hda"))
    if staged:
        for version in get_installed_versions("Houdini"):
            updated: list[str] = []
            for otls in get_dcc_otls_dirs(version):
                for hda in staged:
                    target = otls / hda.name
                    # Only refresh HDAs the user already has installed here — do not
                    # create new ones — and only when the staged copy is newer.
                    if not target.is_file():
                        continue
                    if target.stat().st_mtime >= hda.stat().st_mtime:
                        continue
                    try:
                        shutil.copy2(hda, target)
                        updated.append(str(target))
                        log.info("Auto-update Houdini HDA: %s → %s", hda.name, otls)
                    except OSError as exc:
                        log.warning("Auto-update HDA failed (non-fatal): %s", exc)
            if updated:
                report["houdini"].append({"version": version, "updated": updated})

    return report


def remove_hdas(version: str) -> tuple[bool, str]:
    """Remove FLUX HDAs from every houdiniX.Y/otls/. Returns (success, message)."""
    otls_dirs = get_dcc_otls_dirs(version)
    if not otls_dirs:
        return False, f"Cannot resolve otls directory for Houdini {version}."

    staged = list(_HDA_STAGING_DIR.glob("*.hda"))
    if not staged:
        return True, "No HDAs to remove."

    removed: list[str] = []
    errors: list[str] = []
    for otls in otls_dirs:
        for hda in staged:
            target = otls / hda.name
            if target.is_file():
                try:
                    target.unlink()
                    removed.append(str(target))
                    log.info("HDA removed: %s", target)
                except OSError as exc:
                    errors.append(f"{target}: {exc}")

    if errors:
        return False, f"Partial removal, errors: {'; '.join(errors)}"
    if not removed:
        return True, "HDAs were not installed."
    return True, f"Removed: {', '.join(removed)}"


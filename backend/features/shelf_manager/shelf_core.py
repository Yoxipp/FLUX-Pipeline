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

# Staging dir: copy of the last live-built HDAs, used by an install while Houdini is closed.
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
    if dcc_name == "ZBrush":
        from features.shelf_manager import zbrush_ui
        return zbrush_ui.get_versions()

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
    if dcc_name == "ZBrush":
        from features.shelf_manager import zbrush_ui
        return zbrush_ui.is_installed(version)
    shelf_dir = get_dcc_shelf_dir(dcc_name, version)
    filename = _SHELF_FILENAME.get(dcc_name)
    if shelf_dir is None or filename is None:
        return False
    return (shelf_dir / filename).is_file()


def install_shelf(dcc_name: str, version: str) -> tuple[bool, str]:
    """Copy the bundled shelf file to the DCC user directory.

    For Maya, builds a single Flux shelf from the persisted tool selection.
    For Houdini, also installs the FLUX HDAs into houdiniX.Y/otls/ (non-fatal if it
    fails, reported in the message). Returns (success, message).
    """
    if dcc_name == "Maya":
        return install_flux_shelf(version)
    if dcc_name == "ZBrush":
        # ZBrush "shelf" = the FLUX UI (flux_ui_zbrush.cfg) + the bridge (FLUX menu).
        from features.shelf_manager import zbrush_ui
        return zbrush_ui.install(version)

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

    msg = f"Installed → {dest}"
    if dcc_name == "Houdini":
        # The FLUX HDAs ship with the Houdini shelf (the autostart installs them too).
        # Non-blocking: an HDA failure never fails the shelf install.
        try:
            hda_ok, hda_msg = install_hdas(version)
        except Exception as exc:    # noqa: BLE001
            hda_ok, hda_msg = False, f"Error: {exc}"
        if not hda_ok:
            log.warning("HDA install failed (non-fatal): %s", hda_msg)
        msg += f" | HDA : {hda_msg}" if hda_ok else f" | HDA non installes : {hda_msg}"
        reloaded = _reload_houdini_shelf(dest)
        if reloaded:
            msg += " | shelf rechargee dans Houdini " + ", ".join(f":{p}" for p in reloaded)

    return True, msg


# Houdini reads its shelf files at startup only: an open session kept the old FLUX
# shelf after a reinstall (2026-10-10, no FLUX Work button). Reloaded in place in
# each connected Houdini whose user pref dir holds the installed file.
_RELOAD_SHELF_CODE = """
import os
_dir = os.path.dirname(os.path.dirname(_FLUX_SHELF))
_mine = os.path.normcase(os.path.abspath(hou.homeHoudiniDirectory())) == os.path.normcase(os.path.abspath(_dir))
if _mine:
    hou.shelves.loadFile(_FLUX_SHELF)
result = _mine
"""


def _reload_houdini_shelf(shelf_file: Path) -> list[int]:
    """Reload *shelf_file* in the open Houdini sessions; returns the ports done."""
    try:
        from core.dcc_instances import scan_instances
        from dcc.houdini.client import HoudiniClient

        ports = [i["port"] for i in scan_instances("Houdini") if i.get("connected")]
    except Exception as exc:  # noqa: BLE001 — best effort
        log.debug("Houdini scan for shelf reload failed: %s", exc)
        return []
    done = []
    code = "_FLUX_SHELF = %r\n" % str(shelf_file).replace("\\", "/") + _RELOAD_SHELF_CODE
    for port in ports:
        try:
            resp = HoudiniClient(port=port).run(code, timeout=20.0)
        except Exception as exc:  # noqa: BLE001
            resp = {"ok": False, "error": str(exc)}
        if resp.get("ok") and resp.get("result"):
            done.append(port)
        elif not resp.get("ok"):
            log.warning("Shelf reload in Houdini :%s failed: %s", port, resp.get("error"))
    return done


# ── Maya tools → single Flux shelf ────────────────────────────────────────────
# ONE Flux shelf (shelf_Flux.mel) is generated from the SELECTED tools' buttons:
# each tool source .mel contributes the shelfButtons inside its `global proc`.
# User-facing tools: ANIM (animation), RIG (rigging toolbox), CAM (base Camera Rig)
# and LIGHT (base Light Rig). Order matches the shelf layout. The MAJ pipeline button
# is not a tool (always on the shelf); the Houdini importer HDA is a technical
# dependency installed with the Houdini shelf and the autostart.
MAYA_TOOLS: list[dict] = [
    {"id": "flux_anim", "label": "ANIM",  "filename": "shelf_FluxAnimTool.mel"},
    {"id": "adam_rig",   "label": "RIG",   "filename": "shelf_AntRigToolbox.mel"},
    {"id": "cam_rig",   "label": "CAM",   "filename": "shelf_FluxCamRig.mel"},
    {"id": "light_rig", "label": "LIGHT", "filename": "shelf_FluxLightRig.mel"},
]
# Catalogue ids the saved selection already knew about: a tool added later starts
# checked instead of vanishing from a shelf saved before it existed.
_SHELF_TOOLS_KNOWN_KEY = "maya_shelf_tools_known"
_LEGACY_KNOWN_TOOLS = ("flux_anim", "adam_rig")


def _tool(tool_id: str) -> dict | None:
    return next((t for t in MAYA_TOOLS if t["id"] == tool_id), None)


def list_tools() -> list[dict]:
    """Catalogue des tools Maya (id + label + fichier)."""
    return [dict(t) for t in MAYA_TOOLS]


def get_shelf_tool_selection() -> list[str]:
    """Return the persisted tool selection (defaults to all tools)."""
    sel = config.get(_SHELF_TOOLS_KEY)
    if not isinstance(sel, list):
        return [t["id"] for t in MAYA_TOOLS]
    known = config.get(_SHELF_TOOLS_KNOWN_KEY)
    if not isinstance(known, list):
        known = list(_LEGACY_KNOWN_TOOLS)
    # may be empty if all unchecked; tools newer than the saved choice start checked
    return [t["id"] for t in MAYA_TOOLS if t["id"] in sel or t["id"] not in known]


def set_shelf_tool_selection(ids: list[str]) -> None:
    config.set(_SHELF_TOOLS_KEY, [i for i in ids if _tool(i)])
    config.set(_SHELF_TOOLS_KNOWN_KEY, [t["id"] for t in MAYA_TOOLS])


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
    # Pipeline buttons (X4 "MAJ"): always on the shelf, whatever tools are picked.
    pipeline = _RESOURCES_ROOT / "maya" / "shelf_FluxPipeline.mel"
    if pipeline.is_file():
        body = _extract_shelf_body(pipeline.read_text(encoding="utf-8"))
        if body:
            bodies.append(f"    // ── FLUX ──\n{body}")
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

    For Houdini the HDAs are kept: the autostart still relies on them.
    Returns (success, message).
    """
    if dcc_name == "ZBrush":
        from features.shelf_manager import zbrush_ui
        return zbrush_ui.remove(version)
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

    # Houdini HDAs are NOT removed here: the autostart keeps using them (its
    # uninstall removes them).

    return True, f"Removed: {target}"


def find_flux_maya_traces(version: str) -> list[Path]:
    """FLUX shelves (shelf_Flux*.mel, current + older names) and shelf icons in Maya <version> prefs."""
    found: list[Path] = []
    shelf_dir = get_dcc_shelf_dir("Maya", version)
    if shelf_dir is None:
        return found
    try:
        found += sorted(shelf_dir.glob("shelf_Flux*.mel"))
    except OSError:
        pass
    icons_src = _RESOURCES_ROOT / "maya" / "icons"
    if icons_src.is_dir():
        found += [shelf_dir.parent / "icons" / png.name for png in icons_src.glob("*.png")
                  if (shelf_dir.parent / "icons" / png.name).is_file()]
    return found


def remove_flux_maya_traces(version: str) -> list[str]:
    """Delete the FLUX shelves + icons of Maya <version> (FLUX uninstaller). Best-effort.

    Only files named after what FLUX ships are touched; the user's own shelves stay.
    The copy in the Maya install dir is removed too when it is writable.
    """
    removed: list[str] = []
    targets = find_flux_maya_traces(version)
    install_dir = _get_maya_install_shelf_dir(version)
    if install_dir is not None:
        try:
            targets += sorted(install_dir.glob("shelf_Flux*.mel"))
        except OSError:
            pass
    for f in targets:
        try:
            f.unlink()
            removed.append(str(f))
        except OSError as exc:
            log.warning("Uninstall: could not delete %s: %s", f, exc)
    return removed


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


def purge_hda_backups(dirs: list[Path]) -> int:
    """Delete the ``backup/flux_*_bak*.hda`` copies Houdini writes each time a FLUX HDA
    is saved over itself (hundreds after a few rebuilds). Other studios' backups are
    left alone; an emptied backup folder is removed. Returns the number of files."""
    removed = 0
    for base in dirs:
        backup = Path(base) / "backup"
        if not backup.is_dir():
            continue
        for f in backup.glob("flux_*_bak*.hda"):
            try:
                f.unlink()
                removed += 1
            except OSError as exc:
                log.debug("HDA backup not removed %s: %s", f, exc)
        try:
            backup.rmdir()          # only succeeds when empty
        except OSError:
            pass
    if removed:
        log.info("Removed %d Houdini HDA backup file(s)", removed)
    return removed


# (builder "module:function", output file, hou category expression, node type name) of
# every FLUX HDA, in build order: the LOP importer reads the SOP definition built before it.
_HDA_BUILDS: tuple[tuple[str, str, str, str], ...] = (
    ("flux_importer_hda:build_hda",     "flux_importer.hda",     "hou.sopNodeTypeCategory()", "flux_importer"),
    ("flux_importer_lop_hda:build_hda", "flux_importer_lop.hda", "hou.lopNodeTypeCategory()", "flux_importer"),
    ("flux_exporter_hda:build_hda",     "flux_exporter.hda",     "hou.sopNodeTypeCategory()", "flux_exporter"),
    ("flux_exporter_hda:build_hda_lop", "flux_exporter_lop.hda", "hou.lopNodeTypeCategory()", "flux_exporter"),
    ("flux_exporter_hda:build_hda_obj", "flux_exporter_obj.hda", "hou.objNodeTypeCategory()", "flux_exporter"),
    ("flux_anim_hda:build_hda",         "flux_anim.hda",         "hou.lopNodeTypeCategory()", "flux_anim"),
    ("flux_lighting_hda:build_hda",     "flux_lighting.hda",     "hou.lopNodeTypeCategory()", "flux_lighting"),
    ("flux_shot_switch_hda:build_hda",  "flux_shot.hda",         "hou.lopNodeTypeCategory()", "flux_shot"),
    ("flux_render_hda:build_hda",       "flux_render.hda",       "hou.lopNodeTypeCategory()", "flux_render"),
    ("flux_sequence_hda:build_hda",     "flux_sequence.hda",     "hou.lopNodeTypeCategory()", "flux_sequence"),
    ("flux_crowd_hda:build_hda",        "flux_crowd.hda",        "hou.lopNodeTypeCategory()", "flux_crowd"),
    ("flux_work_hda:build_hda",         "flux_work.hda",         "hou.sopNodeTypeCategory()", "flux_work"),
    ("flux_work_hda:build_hda_lop",     "flux_work_lop.hda",     "hou.lopNodeTypeCategory()", "flux_work"),
)

# Runs inside Houdini after the build: makes the definition FLUX just wrote the one
# Houdini uses. Without it, an older definition of the same node type (another otls
# dir, a copy embedded in the .hip, a package path) can stay active, and the rebuilt
# HDA "changes nothing" in the scene (2026-09-25: FLUX Lighting still empty,
# FLUX Import still with its + / - after a reinstall).
_PREFER_CODE = '''
import os
_report = []
for _cat_expr, _name, _path in _FLUX_EXPECTED:
    _cat = eval(_cat_expr)
    _t = hou.nodeType(_cat, _name)
    _row = {"type": _cat.name() + "/" + _name, "file": _path, "ok": False, "others": []}
    if _t is None:
        _row["error"] = "type absent"
        _report.append(_row)
        continue
    _mine = None
    for _d in _t.allInstalledDefinitions():
        _lib = _d.libraryFilePath()
        if os.path.normcase(os.path.abspath(_lib)) == os.path.normcase(os.path.abspath(_path)):
            _mine = _d
        else:
            _row["others"].append(_lib)
    if _mine is None:
        _row["error"] = "definition FLUX non chargee"
    else:
        try:
            _mine.setIsPreferred(True)
        except Exception as _exc:
            _row["error"] = "preferred: " + str(_exc)
        _cur = _t.definition()
        _row["ok"] = _cur is not None and _cur.libraryFilePath() == _mine.libraryFilePath()
        _row["instances"] = len(_t.instances())
    _report.append(_row)
result = _report
'''


def _prefer_built_definitions(built: list[tuple[str, str, Path]]) -> list[dict]:
    """Make the definitions just written the active ones in Houdini; one row per HDA."""
    from dcc.houdini.client import houdini_client

    expected = [(cat, name, str(path)) for cat, name, path in built]
    resp = houdini_client.run(f"_FLUX_EXPECTED = {expected!r}\n" + _PREFER_CODE, timeout=60.0)
    if not resp.get("ok"):
        log.warning("HDA preferred-definition check failed: %s", resp.get("error"))
        return []
    return resp.get("result") or []


def _build_hdas_live(otls_dirs: list[Path]) -> tuple[bool, str]:
    """Build the FLUX HDAs in the connected Houdini into otls_dirs[0], mirror the
    resulting .hda files into the other otls dirs AND refresh the staging copy.

    A live build regenerates the HDA from source, so any fix to the builders
    propagates here, unlike a plain copy of a possibly-stale staged .hda. Each HDA is
    built on its own: one failure no longer drops the others onto their old staged
    copy, and the message names every failure. Requires Houdini connected.
    """
    import importlib

    otls = otls_dirs[0]
    try:
        otls.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, f"Cannot create {otls}: {exc}"

    built: list[tuple[str, str, Path]] = []
    failed: list[str] = []
    for target, filename, category, type_name in _HDA_BUILDS:
        label = filename.removesuffix(".hda")
        module, func = target.split(":")
        try:
            builder = getattr(importlib.import_module(f"dcc.houdini.hda.{module}"), func)
            r = builder(str(otls / filename))
        except Exception as exc:
            r = {"ok": False, "error": str(exc)}
        if r.get("ok"):
            built.append((category, type_name, otls / filename))
        else:
            failed.append(f"{label} : {r.get('error') or 'erreur inconnue'}")
            log.error("Live HDA build failed (%s): %s", label, r.get("error"))

    built_files = sorted({p.name for _, _, p in built})
    # Mirror into the other otls roots so Houdini finds it wherever it reads.
    for other in otls_dirs[1:]:
        try:
            other.mkdir(parents=True, exist_ok=True)
            for name in built_files:
                shutil.copy2(otls / name, other / name)
        except OSError as exc:
            log.warning("Could not mirror live-built HDA to %s: %s", other, exc)
    # Refresh the offline staging copy so later offline installs use the fix too.
    try:
        _HDA_STAGING_DIR.mkdir(parents=True, exist_ok=True)
        for name in built_files:
            shutil.copy2(otls / name, _HDA_STAGING_DIR / name)
    except OSError as exc:
        log.warning("Could not refresh HDA staging copy: %s", exc)
    purge_hda_backups([*otls_dirs, _HDA_STAGING_DIR])

    notes: list[str] = []
    try:
        rows = _prefer_built_definitions(built)
    except Exception as exc:
        rows = []
        log.warning("HDA preferred-definition check errored: %s", exc)
    for row in rows:
        if not row.get("ok"):
            notes.append(f"{row.get('type')} : {row.get('error') or 'ancienne definition active'}")
        elif row.get("others"):
            notes.append(f"{row.get('type')} : autre(s) copie(s) ignoree(s) {', '.join(row['others'])}")

    msg = f"HDAs construits ({len(built_files)}) -> {otls}"
    if failed:
        msg += " | ECHEC : " + " ; ".join(failed)
    if notes:
        msg += " | " + " ; ".join(notes)
    return not failed, msg


def install_hdas(version: str) -> tuple[bool, str]:
    """Install the FLUX HDAs into EVERY houdiniX.Y/otls/ Houdini may read.

    When Houdini is connected, the HDAs are BUILT LIVE from source so builder fixes
    propagate (idempotent, same filenames, no duplicates). When Houdini is offline,
    fall back to copying the last live build staged in %APPDATA%/FLUX/dcc/houdini/.
    Returns (success, message).
    """
    otls_dirs = get_dcc_otls_dirs(version)
    if not otls_dirs:
        return False, f"Cannot resolve otls directory for Houdini {version}."
    purge_hda_backups(otls_dirs)     # leftovers of earlier rebuilds

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
        # A failed live build is reported as a failure: the staged copy of the HDA
        # that failed is an OLD build, so "installed" would hide that nothing changed.
        log.warning("Live HDA build failed: %s", msg)
        return False, msg + " | les HDA en echec gardent leur ancienne version"

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
    Houdini: nothing. The HDAs are only built live from source; copying staged
            files here used to put old builds back over fresh ones (2026-09-25).

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

    # ── Maya: refresh a stale autostart block in userSetup.py ─────────────────
    # install() only rewrites blocks that differ from the current one. This carries
    # the loopback-only commandPort (security S3) onto machines that installed the
    # autostart before, without touching machines where it was never installed.
    try:
        from dcc.maya import autostart as maya_autostart
        if maya_autostart.is_installed():
            result = maya_autostart.install()
            if result.get("message") not in (None, "already_installed"):
                log.info("Auto-update Maya autostart: %s", result.get("message"))
                report["maya"].append({"autostart": result})
    except Exception as exc:  # never block startup
        log.warning("Auto-update Maya autostart failed (non-fatal): %s", exc)

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


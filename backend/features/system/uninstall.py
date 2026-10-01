# uninstall.py - remove everything FLUX added to this machine (FLUX uninstaller).
#
# Run by the NSIS uninstaller ("Uninstall FLUX.exe" next to FLUX.exe) through
# `flux_backend.exe --uninstall-cleanup`, before the app files are deleted. Never run
# during an update (installer.nsh skips it). Settings > "Desinstaller FLUX" only
# launches that uninstaller, so there is a single cleanup path.
#
# Removed: what FLUX wrote into the DCCs (autostart blocks, bridges, plugins, HDAs,
# shelves, Houdini flux.json package / $FLUX, ZBrush PYTHONPATH entry, ZBrush UI,
# Painter presets), the Marvelous helper DLLs FLUX downloaded and FLUX temp logs.
# The app data dirs (%APPDATA%/FLUX, %APPDATA%/FluxPipeline, %LOCALAPPDATA%/FLUX) are
# deleted by NSIS once this process has exited (the backend logs into them).
#
# Never touched: Python and its packages (FLUX does not install Python; a package
# installed into the user's Python stays there), the DCCs themselves, the projects
# and the FLUX root folder, and the user's own content in shared startup files
# (only the FLUX block is cut out of userSetup.py / 123.py / init.py ...).

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from core.logger import get_logger

log = get_logger(__name__)

# DCC key (config dcc_paths) -> (label, autostart module path). Same set as routers/dcc.py.
_AUTOSTART_MODULES: dict[str, tuple[str, str]] = {
    "maya":               ("Maya", "dcc.maya.autostart"),
    "nuke":               ("Nuke", "dcc.nuke.autostart"),
    "zbrush":             ("ZBrush", "dcc.zbrush.autostart"),
    "substance_painter":  ("Substance Painter", "dcc.substance_painter.autostart"),
    "substance_designer": ("Substance Designer", "dcc.substance_designer.autostart"),
    "mari":               ("Mari", "dcc.mari.autostart"),
    "marvelous":          ("Marvelous Designer", "dcc.marvelous.autostart"),
}

# Shown in Settings before uninstalling: what is left on the machine.
KEPT = [
    "Python et ses paquets (FLUX n'installe pas Python, rien n'y est retire)",
    "Les logiciels eux-memes (Maya, Houdini, Nuke, ZBrush, Substance, Mari, Marvelous...)",
    "Les projets et le dossier FLUX (DOSSIER_PROJETS, USER, CONFIG)",
    "Ton propre contenu dans userSetup.py, 123.py, init.py... (seul le bloc FLUX est retire)",
    "Un preset Painter FLUX que tu as modifie",
]


def app_data_dirs() -> list[Path]:
    """Per-user dirs FLUX itself writes (config, prefs, logs, staged HDAs, helper DLLs)."""
    appdata = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    local = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return [appdata / "FLUX", appdata / "FluxPipeline", local / "FLUX"]


def _temp_traces() -> list[Path]:
    """FLUX bridge logs / reports / mailboxes in the temp dir."""
    tmp = Path(tempfile.gettempdir())
    try:
        return sorted(tmp.glob("flux_*"))
    except OSError:
        return []


def _exe(dcc_key: str) -> str | None:
    try:
        from core import config
        return (config.get("dcc_paths", {}) or {}).get(dcc_key)
    except Exception:  # config unreadable: every uninstall() works without an exe
        return None


def _autostart(module_path: str):
    import importlib
    return importlib.import_module(module_path)


# ── plan (read only) ─────────────────────────────────────────────────────────

def plan() -> dict:
    """What an uninstall would remove right now, and what it keeps. Reads only."""
    remove: list[dict] = []

    def add(label: str, paths: list) -> None:
        if paths:
            remove.append({"label": label, "paths": [str(p) for p in paths]})

    from dcc.houdini import autostart as houdini
    for prefs in houdini.all_user_prefs_dirs():
        add(f"Houdini {prefs.name[len('houdini'):]} ({prefs})", houdini.find_traces(prefs))

    for key, (label, module_path) in _AUTOSTART_MODULES.items():
        try:
            mod = _autostart(module_path)
            exe = _exe(key)
            if mod.is_installed(exe):
                startup = mod.get_startup_file(exe)
                add(f"{label} : bridge / autostart", [startup or label])
        except Exception as exc:
            log.warning("Uninstall plan: %s check failed: %s", label, exc)

    try:
        from features.shelf_manager import shelf_core
        for version in shelf_core.get_installed_versions("Maya"):
            add(f"Maya {version} : shelf FLUX", shelf_core.find_flux_maya_traces(version))
    except Exception as exc:
        log.warning("Uninstall plan: Maya shelves check failed: %s", exc)

    try:
        from features.shelf_manager import zbrush_ui
        for version in zbrush_ui.get_versions():
            if zbrush_ui.is_installed(version):
                add(f"ZBrush {version} : interface FLUX", [f"ZBrush {version}"])
    except Exception as exc:
        log.warning("Uninstall plan: ZBrush UI check failed: %s", exc)

    try:
        from dcc.substance_painter.presets import find_installed_presets
        add("Substance Painter : presets d'export FLUX", find_installed_presets())
    except Exception as exc:
        log.warning("Uninstall plan: Painter presets check failed: %s", exc)

    add("Donnees de FLUX sur ce poste (config, preferences, logs)",
        [d for d in app_data_dirs() if d.exists()])
    add("Fichiers temporaires FLUX", _temp_traces())
    return {"remove": remove, "keep": KEPT}


# ── cleanup ──────────────────────────────────────────────────────────────────

def _step(report: list[dict], label: str, fn: Callable[[], object]) -> None:
    """Run one cleanup step; a failure is reported, never raised (keep uninstalling)."""
    try:
        detail = fn()
        report.append({"step": label, "ok": True, "detail": detail})
    except Exception as exc:  # noqa: BLE001 - one DCC must never block the others
        log.warning("Uninstall step %s failed: %s", label, exc)
        report.append({"step": label, "ok": False, "detail": str(exc)})


def _remove_houdini() -> list[str]:
    from dcc.houdini import autostart as houdini
    changed: list[str] = []
    for prefs in houdini.all_user_prefs_dirs():
        changed += houdini.purge_prefs_dir(prefs)
    return changed


def _remove_maya_shelves() -> list[str]:
    from features.shelf_manager import shelf_core
    removed: list[str] = []
    for version in shelf_core.get_installed_versions("Maya"):
        removed += shelf_core.remove_flux_maya_traces(version)
    return removed


def _remove_zbrush_ui() -> list[str]:
    from features.shelf_manager import zbrush_ui
    done: list[str] = []
    for version in zbrush_ui.get_versions():
        ok, msg = zbrush_ui.remove(version)
        if ok:
            done.append(msg)
    return done


def _remove_painter_presets() -> list[str]:
    from dcc.substance_painter.presets import remove_presets
    return remove_presets()


def _remove_temp() -> list[str]:
    removed: list[str] = []
    for p in _temp_traces():
        try:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
            removed.append(str(p))
        except OSError:
            continue    # a log still open by a running DCC: left to the OS temp cleanup
    return removed


def _remove_marvelous_pylib() -> str:
    from dcc.marvelous.autostart import pylib_dir
    d = pylib_dir()
    if d.is_dir():
        shutil.rmtree(d)
        return str(d)
    return "absent"


def _startup_files() -> list[Path]:
    """Shared startup scripts of the other DCCs that may have held a FLUX block."""
    files: list[Path] = []
    try:
        from dcc.maya import autostart as maya
        app_dir = maya._get_maya_app_dir()
        if app_dir is not None:
            files += maya._discover_startup_files(app_dir)
    except Exception as exc:
        log.warning("Uninstall: Maya startup files not listed: %s", exc)
    try:
        from dcc.nuke import autostart as nuke
        files += [nuke._nuke_home() / "init.py", nuke._nuke_home() / "menu.py"]
    except Exception as exc:
        log.warning("Uninstall: Nuke startup files not listed: %s", exc)
    try:
        from dcc.mari import autostart as mari
        files += [d / mari._INIT_NAME for d in mari._scripts_dirs()]
    except Exception as exc:
        log.warning("Uninstall: Mari startup files not listed: %s", exc)
    return files


def _drop_empty_startup_files() -> list[str]:
    """After the FLUX blocks are cut out, delete a startup script left empty: FLUX
    created it. One that still holds the user's own code is kept."""
    removed: list[str] = []
    for f in _startup_files():
        try:
            if f.is_file() and not f.read_text(encoding="utf-8", errors="replace").strip():
                f.unlink()
                removed.append(str(f))
        except OSError:
            continue
    return removed


def _remove_empty_docs_dir() -> list[str]:
    """Documents/FLUX (Marvelous bridge folder): drop the folders left empty."""
    from dcc.user_dirs import documents_dir
    base = documents_dir() / "FLUX"
    removed: list[str] = []
    if not base.is_dir():
        return removed
    for d in sorted((p for p in base.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True) + [base]:
        try:
            if not any(d.iterdir()):
                d.rmdir()
                removed.append(str(d))
        except OSError:
            continue
    return removed


def run_cleanup() -> list[dict]:
    """Remove every FLUX trace from the DCCs and the temp dir. Returns the step report."""
    report: list[dict] = []
    _step(report, "houdini", _remove_houdini)
    for key, (label, module_path) in _AUTOSTART_MODULES.items():
        _step(report, key, lambda m=module_path, k=key: _autostart(m).uninstall(_exe(k)))
    _step(report, "empty_startup_files", _drop_empty_startup_files)
    _step(report, "maya_shelves", _remove_maya_shelves)
    _step(report, "zbrush_ui", _remove_zbrush_ui)
    _step(report, "painter_presets", _remove_painter_presets)
    _step(report, "marvelous_pylib", _remove_marvelous_pylib)
    _step(report, "documents_flux_dir", _remove_empty_docs_dir)
    _step(report, "temp", _remove_temp)
    return report


def run_cleanup_cli() -> int:
    """Entry of `flux_backend.exe --uninstall-cleanup`. Always exits 0: a failed step
    must not stop the uninstaller from removing the app itself."""
    report = run_cleanup()
    for row in report:
        line = f"[{'OK' if row['ok'] else 'ECHEC'}] {row['step']}: {row['detail']}"
        log.info("Uninstall %s", line)
        try:
            print(line, flush=True)
        except Exception:  # windowed exe: no console to print to
            pass
    return 0

"""
Old FLUX files left in the DCC prefs after a shelf reinstall (2026-10-10).

``scan(dcc, version)`` lists what is FLUX's AND no longer the real install, with the
reason; the Shelf Manager shows it in a checklist after "Installer" and ``remove``
deletes the ticked ones. Safety:

* only files FLUX ships are ever listed (Houdini ``flux_*.hda`` whose definitions are
  FLUX node types, Maya ``shelf_Flux*.mel``): an artist's own HDA or shelf never is;
* ``remove`` deletes a path only if a fresh scan still lists it: the client cannot
  make the backend delete an arbitrary file.

Houdini rules (one version): an HDA FLUX no longer ships (old name), a copy outside the
otls dir the running Houdini reads (duplicate: Houdini shows "other copies ignored"),
a backup of an older build. Maya: an older FLUX shelf name beside shelf_Flux.mel.
"""

from __future__ import annotations

from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

# Bytes every FLUX HDA holds: its node types are named flux_* (Sop/flux_importer...).
_FLUX_TYPE_MARK = b"/flux_"
MAYA_SHELF = "shelf_Flux.mel"


def _is_flux_hda(path: Path) -> bool:
    if not (path.is_file() and path.name.lower().startswith("flux_") and path.suffix.lower() == ".hda"):
        return False
    try:
        with path.open("rb") as fh:
            return _FLUX_TYPE_MARK in fh.read(256 * 1024)
    except OSError:
        return False


def _norm(path: Path) -> str:
    import os

    return os.path.normcase(os.path.abspath(str(path)))


def active_houdini_otls(version: str) -> Path | None:
    """otls dir of the prefs the connected Houdini reads, when it is this *version*.
    None when Houdini is closed or another version: nothing is called a duplicate."""
    try:
        from dcc.houdini.client import houdini_client

        resp = houdini_client.run(
            'result = [hou.homeHoudiniDirectory(), "%d.%d" % hou.applicationVersion()[:2]]', timeout=10.0)
    except Exception as exc:  # noqa: BLE001 — best effort
        log.debug("Active Houdini prefs lookup failed: %s", exc)
        return None
    if not resp.get("ok") or not isinstance(resp.get("result"), list):
        return None
    home, running = resp["result"]
    if str(running) != str(version):
        return None
    return Path(home) / "otls"


def _houdini(version: str, active: Path | None) -> list[dict]:
    from features.shelf_manager import shelf_core

    current = {filename for _, filename, _, _ in shelf_core._HDA_BUILDS}
    dirs = list(shelf_core.get_dcc_otls_dirs(version))
    if active is not None and _norm(active) not in {_norm(d) for d in dirs}:
        dirs.insert(0, active)
    found: list[dict] = []
    for otls in dirs:
        try:
            files = sorted(otls.glob("flux_*.hda")) + sorted((otls / "backup").glob("flux_*.hda"))
        except OSError:
            continue
        for f in files:
            if not _is_flux_hda(f):
                continue
            if f.parent.name == "backup":
                reason = "sauvegarde d'une ancienne construction"
            elif f.name not in current:
                reason = "HDA FLUX qui n'existe plus (ancien nom)"
            elif active is not None and _norm(f.parent) != _norm(active):
                reason = f"copie en double : Houdini lit {active}"
            else:
                continue
            found.append({"path": str(f), "reason": reason})
    # The offline staging copy (FLUX's own folder): only old names are stale there.
    try:
        staged = sorted(shelf_core._HDA_STAGING_DIR.glob("flux_*.hda"))
    except OSError:
        staged = []
    for f in staged:
        if f.name not in current and _is_flux_hda(f):
            found.append({"path": str(f), "reason": "copie FLUX hors ligne d'une HDA qui n'existe plus"})
    return found


def _maya(version: str) -> list[dict]:
    from features.shelf_manager import shelf_core

    shelf_dir = shelf_core.get_dcc_shelf_dir("Maya", version)
    if shelf_dir is None:
        return []
    try:
        shelves = sorted(shelf_dir.glob("shelf_Flux*.mel"))
    except OSError:
        return []
    return [{"path": str(f), "reason": f"ancien shelf FLUX (le shelf actuel est {MAYA_SHELF})"}
            for f in shelves if f.name != MAYA_SHELF and f.is_file()]


def scan(dcc: str, version: str) -> list[dict]:
    """[{path, reason}] of old FLUX files for *dcc* *version* (empty for a DCC without
    stale-file rules)."""
    if dcc == "Houdini":
        return _houdini(version, active_houdini_otls(version))
    if dcc == "Maya":
        return _maya(version)
    return []


_FORGET_CODE = """
_gone = %r
import os
_n = lambda p: os.path.normcase(os.path.abspath(p))
for _f in hou.hda.loadedFiles():
    if _n(_f) in {_n(p) for p in _gone}:
        try:
            hou.hda.uninstallFile(_f, change_oplibraries_file=False)
        except Exception:
            pass
result = True
"""


def _forget_in_houdini(paths: list[str]) -> None:
    """The open Houdini stops using the deleted HDA files (best effort)."""
    code = _FORGET_CODE % [p.replace(chr(92), "/") for p in paths]
    try:
        from dcc.houdini.client import houdini_client

        houdini_client.run(code, timeout=20.0)
    except Exception as exc:  # noqa: BLE001
        log.debug("Houdini uninstall of removed HDAs failed: %s", exc)


def remove(dcc: str, version: str, paths: list[str]) -> dict:
    """Delete the *paths* a fresh scan still lists. Returns {removed, skipped, failed}."""
    allowed = {_norm(Path(item["path"])) for item in scan(dcc, version)}
    out = {"removed": [], "skipped": [], "failed": []}
    for raw in paths:
        p = Path(raw)
        if _norm(p) not in allowed:
            out["skipped"].append(raw)
            continue
        try:
            p.unlink()
            out["removed"].append(raw)
            log.info("Old FLUX file removed: %s", p)
        except OSError as exc:
            out["failed"].append(f"{raw} : {exc}")
    if dcc == "Houdini" and out["removed"]:
        _forget_in_houdini(out["removed"])
    for raw in out["removed"]:
        backup = Path(raw).parent
        if backup.name == "backup":
            try:
                if not any(backup.iterdir()):
                    backup.rmdir()
            except OSError:
                pass
    return out

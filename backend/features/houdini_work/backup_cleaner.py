"""
Cleaner of the Houdini backups of FLUX Work (ADR 0090 point 8, ADR 0092).

Only two kinds of files are ever touched, never a ``wNNN`` version nor a publish:

* Houdini backups inside a FLUX Work task folder (``<dept>/work/houdini/<TASK>/``):
  the scene files of its ``backup/`` subfolder and the ``*_bak*`` scenes next to the
  versions (Houdini "Save with backup": ``w003_bak1.hip``);
* the FLUX autosave copies of this machine (``%LOCALAPPDATA%/FLUX/houdini_autosave``)
  of the project, ``a0`` / ``a1`` / ``a2`` per work.

Rule: a file older than N days (advanced setting ``houdini_backup_keep_days``, default
14, 0 = cleaner off) is deleted, except the newest file of its scene, always kept.
Deletion is final (no undo, these are copies): ``scan`` lists, the user (or a supervisor
from the 13h / 18h panel) validates, ``apply`` deletes the validated ids that a fresh
scan still lists and writes a journal in ``<project>/.flux_cleanup/houdini_backups/``.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

from core.logger import get_logger
from features.houdini_work import autosave, work_store

log = get_logger(__name__)

ENV_DAYS = "FLUX_HOUDINI_BACKUP_KEEP_DAYS"
DEFAULT_DAYS = 14
MAX_DAYS = 365
JOURNAL_DIR = (".flux_cleanup", "houdini_backups")
BACKUP_SUBDIR = "backup"

_SKIP_DIRS = {".flux_cleanup", "_backup_flux", ".git", "node_modules"}
_BAK_RE = re.compile(r"^(?P<scene>.+?)_bak\d*$", re.IGNORECASE)
_VERSION_RE = re.compile(r"^w\d{3,}$", re.IGNORECASE)
_HIP_EXTS = tuple(e.lower() for e in work_store.HIP_EXTS)
_DAY_S = 86400.0


def keep_days() -> int:
    """Age in days past which a backup goes; 0 = cleaner off."""
    raw = os.environ.get(ENV_DAYS)
    if raw is None or not raw.strip():
        return DEFAULT_DAYS
    try:
        return max(0, min(MAX_DAYS, int(float(raw))))
    except ValueError:
        return DEFAULT_DAYS


def _is_scene(path: Path) -> bool:
    return path.suffix.lower() in _HIP_EXTS


def backup_scene(path: Path, in_backup_dir: bool) -> str | None:
    """Scene a backup file belongs to (``w003`` for ``w003_bak2.hip``), None = not a
    backup. A version name (``w003.hip``) is never a backup, even in ``backup/``."""
    if not _is_scene(path):
        return None
    stem = path.stem
    if _VERSION_RE.match(stem):
        return None
    match = _BAK_RE.match(stem)
    if match:
        return match.group("scene")
    return stem if in_backup_dir else None


def _task_dirs(project: Path):
    """FLUX Work task folders of the project (``.../work/houdini/<TASK>``)."""
    for dirpath, dirnames, _files in os.walk(project):
        here = Path(dirpath)
        if here.name.lower() == work_store.WORK_SUBDIR[1] and here.parent.name.lower() == work_store.WORK_SUBDIR[0]:
            for name in dirnames:
                yield here / name
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and not d.startswith(".")]


def _stat(path: Path) -> tuple[float, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime, st.st_size


def _project_candidates(project: Path) -> dict[tuple[str, str], list[tuple[str, Path]]]:
    """(group, scene) -> [(id, path)] of the Houdini backups in the work folders."""
    groups: dict[tuple[str, str], list[tuple[str, Path]]] = {}
    for task in _task_dirs(project):
        places = [(task, False), (task / BACKUP_SUBDIR, True)]
        for folder, in_backup in places:
            if not folder.is_dir():
                continue
            for path in folder.iterdir():
                if not path.is_file():
                    continue
                scene = backup_scene(path, in_backup)
                if scene is None:
                    continue
                rel = path.relative_to(project).as_posix()
                groups.setdefault((task.as_posix(), scene.lower()), []).append((f"p|{rel}", path))
    return groups


def _project_prefix(project_name: str) -> str:
    return autosave.scene_key(project_name, "", "", "").split("__")[0] + "__"


def _autosave_candidates(project_name: str, root: Path) -> dict[tuple[str, str], list[tuple[str, Path]]]:
    """(group, scene) -> [(id, path)] of this machine's autosave copies of the project."""
    groups: dict[tuple[str, str], list[tuple[str, Path]]] = {}
    if not root.is_dir():
        return groups
    prefix = _project_prefix(project_name)
    for directory in root.iterdir():
        if not directory.is_dir() or not directory.name.startswith(prefix):
            continue
        for path, _mtime in autosave.list_autosaves(directory):
            groups.setdefault((directory.name, "autosave"), []).append(
                (f"a|{directory.name}/{path.name}", path))
    return groups


def _plan(project: Path, project_name: str, days: int, now: float, root: Path) -> tuple[list[dict], int]:
    """Files to delete (oldest first) and the number of backups kept."""
    items: list[dict] = []
    kept = 0
    limit = now - days * _DAY_S
    sources = [("projet", _project_candidates(project)), ("autosave", _autosave_candidates(project_name, root))]
    for where, groups in sources:
        for (_group, scene), files in groups.items():
            stats = [(fid, path, _stat(path)) for fid, path in files]
            stats = [(fid, path, st) for fid, path, st in stats if st is not None]
            if not stats:
                continue
            stats.sort(key=lambda x: x[2][0], reverse=True)
            kept += 1                                # the newest of a scene always stays
            for fid, path, (mtime, size) in stats[1:]:
                if mtime >= limit:
                    kept += 1
                    continue
                items.append({"id": fid, "where": where, "scene": scene, "name": path.name,
                              "path": fid[2:], "size": size, "mtime": mtime,
                              "age_days": int((now - mtime) // _DAY_S)})
    items.sort(key=lambda i: i["mtime"])
    return items, kept


def _resolve(project: Path, root: Path, fid: str) -> Path:
    kind, _, rel = fid.partition("|")
    return (project if kind == "p" else root) / rel


def scan(project_path: str | Path, project_name: str, *, days: int | None = None,
         now: float | None = None, root: str | Path | None = None) -> dict:
    """What the cleaner would delete in the project and this machine's autosaves."""
    days = keep_days() if days is None else days
    if days <= 0:
        return {"enabled": False, "days": 0, "items": [], "kept": 0, "total_size": 0}
    project = Path(project_path)
    root_p = Path(root) if root is not None else autosave.autosave_root()
    items, kept = _plan(project, project_name, days, time.time() if now is None else now, root_p)
    return {"enabled": True, "days": days, "items": items, "kept": kept,
            "total_size": sum(i["size"] for i in items)}


def apply(project_path: str | Path, project_name: str, ids: list[str], *, days: int | None = None,
          now: float | None = None, root: str | Path | None = None) -> dict:
    """Delete the picked ids that a fresh scan still lists (final); write the journal."""
    project = Path(project_path)
    root_p = Path(root) if root is not None else autosave.autosave_root()
    fresh = scan(project, project_name, days=days, now=now, root=root_p)
    allowed = {i["id"]: i for i in fresh["items"]}
    deleted: list[dict] = []
    errors: list[str] = []
    for fid in dict.fromkeys(ids):
        item = allowed.get(fid)
        if item is None:
            errors.append(f"{fid[2:]} : plus a nettoyer, garde")
            continue
        path = _resolve(project, root_p, fid)
        try:
            path.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            errors.append(f"{item['path']} : {exc}")
            continue
        deleted.append({"where": item["where"], "path": item["path"], "size": item["size"]})
    journal = ""
    if deleted:
        journal = datetime.now().strftime("%Y%m%d-%H%M%S")
        jdir = project.joinpath(*JOURNAL_DIR)
        try:
            jdir.mkdir(parents=True, exist_ok=True)
            (jdir / f"{journal}.json").write_text(
                json.dumps({"days": fresh["days"], "deleted": deleted}, indent=1), encoding="utf-8")
        except OSError as exc:
            errors.append(f"journal non ecrit : {exc}")
            journal = ""
    freed = sum(d["size"] for d in deleted)
    log.info("Houdini backups %s: %d deleted (%d bytes), %d error(s)", project_name, len(deleted), freed, len(errors))
    return {"deleted": len(deleted), "freed": freed, "errors": errors, "journal": journal}

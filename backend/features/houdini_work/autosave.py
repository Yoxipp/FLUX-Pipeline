"""
FLUX Work autosave and recovery (ADR 0090 point 6).

Houdini (the FLUX Work HDA) writes a copy of the bound scene every N minutes into a
machine-local folder, 3 rotating copies per work, never on the project share and never
over a real ``wNNN``. This module holds the parts that need no Houdini:

* ``scene_key`` / ``autosave_dir``: where the copies of one work live;
* ``pick_slot``: which of the rotating copies the next autosave overwrites;
* ``newer_autosave``: the copy worth proposing at opening (newer than the work file);
* ``recover``: the accepted copy becomes the next version ``wNNN+1`` (never an overwrite);
* ``interval_minutes``: the machine setting (advanced switch), 0 = autosave off.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

from core.logger import get_logger
from features.houdini_work import work_store

log = get_logger(__name__)

KEEP = 3                      # rotating copies per work
DEFAULT_MINUTES = 5
MAX_MINUTES = 120
ENV_MINUTES = "FLUX_HOUDINI_AUTOSAVE_MINUTES"
# An autosave written within this many seconds of the version file is not "newer"
# (clock rounding, a save followed at once by a timer tick).
TOLERANCE_S = 2.0
_SLOT_RE = re.compile(r"^a(\d+)(\.hip|\.hiplc|\.hipnc)$", re.IGNORECASE)


def interval_minutes() -> int:
    """Autosave interval of this machine in minutes; 0 = off."""
    raw = os.environ.get(ENV_MINUTES)
    if raw is None or not raw.strip():
        return DEFAULT_MINUTES
    try:
        return max(0, min(MAX_MINUTES, int(float(raw))))
    except ValueError:
        return DEFAULT_MINUTES


def autosave_root() -> Path:
    """``%LOCALAPPDATA%/FLUX/houdini_autosave`` (local disk, never the project share)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "FLUX" / "houdini_autosave"


def scene_key(project: str, seq: str, shot: str, task: str) -> str:
    """Folder name of one work: ``PROJECT__SEQ__SHOT__TASK`` (shot ``_`` for a sequence task)."""
    parts = [str(project or ""), str(seq or ""), str(shot or "") or "_", str(task or "")]
    return "__".join(re.sub(r"[^A-Za-z0-9_-]", "-", p).upper() for p in parts)


def autosave_dir(root: str | Path, project: str, seq: str, shot: str, task: str) -> Path:
    return Path(root) / scene_key(project, seq, shot, task)


def pick_slot(mtimes: dict[int, float | None], keep: int = KEEP) -> int:
    """Slot (0..keep-1) the next autosave writes: the first one never written, else the
    oldest. *mtimes*: slot -> modification time, missing / None = empty."""
    for slot in range(keep):
        if mtimes.get(slot) is None:
            return slot
    return min(range(keep), key=lambda s: (mtimes[s], s))


def list_autosaves(directory: str | Path) -> list[tuple[Path, float]]:
    """[(path, mtime)] of the copies in *directory*, newest first."""
    directory = Path(directory)
    out = []
    if directory.is_dir():
        for path in directory.iterdir():
            if _SLOT_RE.match(path.name) and path.is_file():
                try:
                    out.append((path, path.stat().st_mtime))
                except OSError:
                    continue
    out.sort(key=lambda item: item[1], reverse=True)
    return out


def next_slot_path(directory: str | Path, ext: str, keep: int = KEEP) -> Path:
    """Path the next autosave must be written to (folder created). Older copies with
    another extension (license change) count as that slot and are replaced."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    ext = (ext or ".hip").lower()
    if ext not in work_store.HIP_EXTS:
        raise work_store.WorkError(f"Extension de scene invalide : {ext!r}")
    mtimes: dict[int, float | None] = {}
    for path, mtime in list_autosaves(directory):
        slot = int(_SLOT_RE.match(path.name).group(1))
        if slot < keep:
            mtimes[slot] = mtime
    slot = pick_slot(mtimes, keep)
    for other in work_store.HIP_EXTS:               # one file per slot
        stale = directory / f"a{slot}{other}"
        if other != ext and stale.exists():
            try:
                stale.unlink()
            except OSError:
                pass
    return directory / f"a{slot}{ext}"


def newer_autosave(autosaves: list[tuple[Path, float]], work_mtime: float | None,
                   tolerance: float = TOLERANCE_S) -> Path | None:
    """Newest copy strictly newer than the work file, else None. No work file (None) =
    nothing to compare with, nothing proposed."""
    if work_mtime is None:
        return None
    best = None
    for path, mtime in autosaves:
        if mtime > work_mtime + tolerance and (best is None or mtime > best[1]):
            best = (path, mtime)
    return best[0] if best else None


def candidate(root: str | Path, folder: str | Path, project: str, seq: str, shot: str,
              task: str) -> dict | None:
    """Autosave to propose when the work opens: newer than the newest committed version."""
    latest = work_store.latest_ok(folder)
    if latest is None or not latest.get("hip"):
        return None
    try:
        work_mtime = Path(latest["hip"]).stat().st_mtime
    except OSError:
        return None
    path = newer_autosave(list_autosaves(autosave_dir(root, project, seq, shot, task)), work_mtime)
    if path is None:
        return None
    return {"path": str(path).replace("\\", "/"), "mtime": path.stat().st_mtime,
            "based_on": latest["version"]}


def recover(root: str | Path, folder: str | Path, *, project: str, seq: str, shot: str, task: str,
            author: str = "", host: str = "") -> dict:
    """The newest autosave of the work becomes the next version ``wNNN+1`` (reserved by
    the usual atomic create: an existing version is never overwritten). The copy is kept
    in the autosave folder."""
    folder = Path(folder)
    found = candidate(root, folder, project, seq, shot, task)
    if found is None:
        raise work_store.WorkError("Aucune sauvegarde automatique plus recente")
    source = Path(found["path"])
    latest = work_store.latest_ok(folder) or {}
    reserved = work_store.reserve_version(
        folder, author=author, host=host, based_on=found["based_on"],
        comment="recuperation autosave", houdini_version=latest.get("houdini_version", ""),
        license=latest.get("license", ""), category=latest.get("category", ""), project=project,
        seq=seq, shot=shot, task=task, ext=source.suffix)
    target = Path(reserved["hip"])
    try:
        with open(source, "rb") as src, open(target, "xb") as dst:
            shutil.copyfileobj(src, dst)
    except OSError as exc:
        work_store.abort_version(folder, reserved["version"])
        raise work_store.WorkError(f"Copie de l'autosave impossible : {exc}") from exc
    done = work_store.commit_version(folder, reserved["version"])
    log.info("Autosave recovered: %s -> %s", source, target)
    return {"version": done["version"], "hip": done["hip"], "based_on": found["based_on"]}

"""
FLUX Work: versions of a Houdini work subnet (ADR 0051, step E2).

One folder per (seq, shot, task)::

    <department folder>/work/houdini/<TASK>/
        w000.cpio + w000.json      template (version 0)
        w001.cpio + w001.json ...  versions, never overwritten, no LAST
        lock.json                  indicative lock (who, host, since)

Houdini writes the ``.cpio`` itself (ADR 0005). The backend only handles metadata:
listing, reservation of the next number (exclusive creation of ``wNNN.json``, state
``writing``), commit (``state: ok`` once the cpio is on disk and its hash checked),
the lock and the divergence check. Several artists by mistake (not at the same time)
must never overwrite each other: a number is taken by an atomic create, never reused.
"""

from __future__ import annotations

import json
import os
import re
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from core.logger import get_logger

log = get_logger(__name__)

WORK_SUBDIR = ("work", "houdini")
VERSION_RE = re.compile(r"^w(\d{3,})\.json$")
LOCK_NAME = "lock.json"
STATE_WRITING = "writing"
STATE_OK = "ok"
# A reservation still "writing" after this long is a crashed save (shown, never reused).
STALE_WRITING_S = 15 * 60
_NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class WorkError(ValueError):
    """Bad request on the work store (unknown task, bad name, wrong state)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _check_name(kind: str, value: str) -> str:
    value = (value or "").strip()
    if not _NAME_RE.match(value):
        raise WorkError(f"{kind} invalide : {value!r}")
    return value.upper()


def version_name(number: int) -> str:
    return "w%03d" % number


def _number(version: str) -> int:
    m = re.match(r"^w(\d{3,})$", version or "")
    if not m:
        raise WorkError(f"Version invalide : {version!r}")
    return int(m.group(1))


# ── location ──────────────────────────────────────────────────────────────────

def work_dir(project_path: str | Path, seq: str, shot: str, task: str) -> Path:
    """Folder of a work task. *shot* empty = a sequence task.

    The department folder comes from the TYPE_SHOT token of *task* (``CFX`` ->
    ``shot/{seq}/{shot}/cfx``). A template without ``{shot}`` (``LIGHT`` ->
    ``lighting/{seq}``) gets the shot appended so two shots never share a folder;
    a sequence task uses the sequence folder + the department name."""
    from features.folder_manager.seq_shot_creator import shot_task_template
    from features.folder_manager.tokens import load_tokens
    from features.usd_assembler.shot_stage import seq_dir

    project = Path(project_path)
    seq = _check_name("Sequence", seq)
    task = _check_name("Tache", task)
    shot = _check_name("Shot", shot) if (shot or "").strip() else ""
    tokens = load_tokens(project) or {}
    template = shot_task_template(task, tokens.get("CLASS"), tokens.get("TYPE_SHOT"))
    if not template:
        raise WorkError(f"Tache inconnue (pas de token TYPE_SHOT) : {task}")
    template = template.replace("\\", "/")
    if not shot:
        if "{shot}" in template:
            dept = seq_dir(project, seq) / template.rstrip("/").split("/")[-1]
        else:
            dept = project / template.format(seq=seq, shot="")
    else:
        dept = project / template.format(seq=seq, shot=shot)
        if "{shot}" not in template:
            dept = dept / shot
    return dept.joinpath(*WORK_SUBDIR, task)


# ── versions ──────────────────────────────────────────────────────────────────

def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def list_versions(folder: str | Path) -> list[dict]:
    """Manifests of *folder*, oldest first. A reservation left ``writing`` is flagged
    ``stale`` after STALE_WRITING_S (crashed save)."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    out = []
    now = time.time()
    for path in folder.iterdir():
        m = VERSION_RE.match(path.name)
        if not m:
            continue
        data = _read_json(path) or {"state": "unreadable"}
        data["version"] = version_name(int(m.group(1)))
        data["cpio"] = str(path.with_suffix(".cpio")).replace("\\", "/")
        if data.get("state") == STATE_WRITING:
            try:
                data["stale"] = now - path.stat().st_mtime > STALE_WRITING_S
            except OSError:
                data["stale"] = True
        out.append(data)
    out.sort(key=lambda d: _number(d["version"]))
    return out


def latest_ok(folder: str | Path) -> dict | None:
    """Newest committed version (the template w000 counts)."""
    ok = [v for v in list_versions(folder) if v.get("state") == STATE_OK]
    return ok[-1] if ok else None


def reserve_version(folder: str | Path, *, author: str, host: str = "", based_on: str = "",
                    comment: str = "", houdini_version: str = "", license: str = "",
                    category: str = "", seq: str = "", shot: str = "", task: str = "",
                    template: bool = False) -> dict:
    """Take the next number by creating ``wNNN.json`` exclusively (state ``writing``).
    Two hosts asking at the same time get two different numbers. *template* reserves
    ``w000`` (refused when it already exists). Returns the manifest + target paths."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    taken = [_number(v["version"]) for v in list_versions(folder)]
    number = 0 if template else max([n for n in taken if n > 0] + [0]) + 1
    manifest = {
        "state": STATE_WRITING, "based_on": based_on or "", "author": author or "",
        "host": host or socket.gethostname(), "date": _now(), "comment": comment or "",
        "houdini_version": houdini_version or "", "license": license or "",
        "category": category or "", "seq": seq, "shot": shot, "task": task,
    }
    while True:
        path = folder / (version_name(number) + ".json")
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if template:
                raise WorkError("Le template w000 existe deja") from None
            number += 1
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(manifest, fh, indent=2, ensure_ascii=False)
        break
    version = version_name(number)
    log.info("Work version reserved: %s/%s by %s", folder, version, author)
    return {**manifest, "version": version,
            "cpio": str(folder / (version + ".cpio")).replace("\\", "/"),
            "manifest": str(path).replace("\\", "/")}


def commit_version(folder: str | Path, version: str, *, hash: str = "", size: int = 0,
                   node_types: list | None = None, external_deps: list | None = None,
                   embedded_hdas: list | None = None) -> dict:
    """Mark a reservation ``ok`` once Houdini has renamed the cpio in place. The hash is
    recomputed from the file: a mismatch with the one Houdini sent is refused."""
    from dcc.houdini.hda.flux_work_io import file_hash

    folder = Path(folder)
    _number(version)
    path = folder / (version + ".json")
    manifest = _read_json(path)
    if manifest is None:
        raise WorkError(f"Version inconnue : {version}")
    if manifest.get("state") != STATE_WRITING:
        raise WorkError(f"{version} n'est pas en cours d'ecriture (etat {manifest.get('state')})")
    cpio = folder / (version + ".cpio")
    if not cpio.is_file():
        raise WorkError(f"{version}.cpio absent : la sauvegarde Houdini n'a pas abouti")
    on_disk = file_hash(str(cpio))
    if hash and hash != on_disk:
        raise WorkError(f"{version}.cpio ne correspond pas au contenu envoye par Houdini")
    manifest.update({
        "state": STATE_OK, "hash": on_disk, "size": size or cpio.stat().st_size,
        "node_types": node_types or [], "external_deps": external_deps or [],
        "embedded_hdas": embedded_hdas or [], "committed": _now(),
    })
    _write_json(path, manifest)
    return {**manifest, "version": version}


def abort_version(folder: str | Path, version: str) -> bool:
    """Drop a reservation whose save failed (manifest + leftovers). An ``ok`` version
    is never removed."""
    folder = Path(folder)
    _number(version)
    path = folder / (version + ".json")
    manifest = _read_json(path)
    if manifest is None or manifest.get("state") == STATE_OK:
        return False
    for leftover in (folder / (version + ".cpio.tmp"), folder / (version + ".cpio"), path):
        try:
            leftover.unlink()
        except FileNotFoundError:
            pass
    return True


# ── lock (indicative) ─────────────────────────────────────────────────────────

def read_lock(folder: str | Path) -> dict | None:
    return _read_json(Path(folder) / LOCK_NAME)


def _same_holder(lock: dict, author: str, host: str) -> bool:
    return lock.get("author") == author and lock.get("host") == host


def take_lock(folder: str | Path, *, author: str, host: str, force: bool = False) -> dict:
    """Open the task for writing. Held by someone else -> {ok: False, lock} unless
    *force* ("reprendre"): the takeover is kept in the lock (``taken_from``)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    current = read_lock(folder)
    if current and not _same_holder(current, author, host) and not force:
        return {"ok": False, "lock": current}
    lock = {"author": author, "host": host, "since": _now()}
    if current and not _same_holder(current, author, host):
        lock["taken_from"] = {k: current.get(k) for k in ("author", "host", "since")}
        log.warning("Work lock taken over in %s: %s@%s -> %s@%s", folder,
                    current.get("author"), current.get("host"), author, host)
    _write_json(folder / LOCK_NAME, lock)
    return {"ok": True, "lock": lock}


def release_lock(folder: str | Path, *, author: str, host: str) -> bool:
    """Free the task. Only the holder releases (a stale tab of the old holder after a
    takeover must not free the new one)."""
    path = Path(folder) / LOCK_NAME
    current = _read_json(path)
    if not current or not _same_holder(current, author, host):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


# ── summary ───────────────────────────────────────────────────────────────────

def task_status(folder: str | Path, *, based_on: str = "", author: str = "", host: str = "") -> dict:
    """What the HDA shows: versions, latest ok, lock, read-only flag and divergence
    (the newest version is not the one this session loaded)."""
    versions = list_versions(folder)
    ok = [v for v in versions if v.get("state") == STATE_OK]
    latest = ok[-1]["version"] if ok else ""
    lock = read_lock(folder)
    return {
        "folder": str(Path(folder)).replace("\\", "/"),
        "versions": versions,
        "latest": latest,
        "has_template": any(v["version"] == "w000" for v in ok),
        "lock": lock,
        "read_only": bool(lock) and not _same_holder(lock, author, host),
        "diverged": bool(based_on) and bool(latest) and latest != based_on,
    }

"""
FLUX Work: versions of a Houdini work scene (ADR 0051, ADR 0090: one work = one scene).

One folder per (seq, shot, task)::

    <department folder>/work/houdini/<TASK>/
        w000.hip + w000.json       template (version 0), copied by FLUX
        w001.hipnc + w001.json ... versions, never overwritten, no LAST
        lock.json                  indicative lock (who, host, since)

The scene extension follows the Houdini license that saved it (.hip / .hiplc / .hipnc).
Houdini writes the scene itself (ADR 0005). The backend handles metadata: listing,
reservation of the next number (exclusive creation of ``wNNN.json``, state ``writing``),
commit (``state: ok`` once the scene is on disk), the lock, the divergence check and the
copy of the template into ``w000``. Several artists by mistake (not at the same time)
must never overwrite each other: a number is taken by an atomic create, never reused.
A manifest carries the project / seq / shot / task, so an opened scene knows its task
from its own path (``identify``).
"""

from __future__ import annotations

import json
import os
import re
import shutil
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


# Network a task's content lives in (ADR 0051): SOP for CFX / FX, LOP for LIGHT / RENDER.
TASK_CATEGORY = {"CFX": "Sop", "FX": "Sop", "LIGHT": "Lop", "RENDER": "Lop"}
# Templates (w000 source) shipped with FLUX: <TASK>.hip, else DEFAULT_SOP / DEFAULT_LOP.hip
# by the task's network (built by dcc/houdini/work_template_build.py). A project overrides
# one with <project>/template/houdini_work/<TASK>.hip (or .hiplc / .hipnc).
BUNDLED_TEMPLATES = Path(__file__).resolve().parents[2] / "resources" / "scenes" / "houdini" / "work"
PROJECT_TEMPLATES = ("template", "houdini_work")
# Scene extensions, by Houdini license (same rule as houdini_render_scene.py).
HIP_EXTS = (".hip", ".hiplc", ".hipnc")


def hip_ext_for_license(category: str) -> str:
    """Scene extension Houdini writes under *category* (``hou.licenseCategory()`` name):
    Commercial .hip, Indie .hiplc, anything else (Apprentice, Education...) .hipnc."""
    name = str(category or "").split(".")[-1].strip().lower()
    if name == "commercial":
        return ".hip"
    if name == "indie":
        return ".hiplc"
    return ".hipnc"


def _first_hip(folder: Path, stem: str) -> Path | None:
    for ext in HIP_EXTS:
        path = folder / (stem + ext)
        if path.is_file():
            return path
    return None


def template_hip(project_path: str | Path, task: str) -> tuple[Path | None, str]:
    """(template scene of *task*, "project" | "flux"), (None, "") when there is none.
    FLUX falls back on the default scene of the task's network (SOP or LOP)."""
    task = (task or "").strip().upper()
    own = _first_hip(Path(project_path).joinpath(*PROJECT_TEMPLATES), task) if task else None
    if own is not None:
        return own, "project"
    for stem in (task, "DEFAULT_" + TASK_CATEGORY.get(task, "Sop").upper()):
        bundled = _first_hip(BUNDLED_TEMPLATES, stem) if stem else None
        if bundled is not None:
            return bundled, "flux"
    return None, ""


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
    ``lighting/{seq}`` in a project made before ADR 0055) gets the shot appended so
    two shots never share a folder; a sequence task drops the shot level
    (``shot/{seq}/{shot}/lighting`` -> ``shot/SEQ/lighting``)."""
    from features.folder_manager.seq_shot_creator import shot_task_template
    from features.folder_manager.tokens import load_tokens

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
        # The template without its shot level: render/{seq}/{shot} -> render/SEQ,
        # shot/{seq}/{shot}/fx -> shot/SEQ/fx, lighting/{seq} -> lighting/SEQ.
        parts = [p for p in template.format(seq=seq, shot="").split("/") if p]
        dept = project.joinpath(*parts)
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
        hip = _first_hip(folder, data["version"])
        data["hip"] = str(hip).replace("\\", "/") if hip else ""
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
                    project: str = "", ext: str = "", template: bool = False) -> dict:
    """Take the next number by creating ``wNNN.json`` exclusively (state ``writing``).
    Two hosts asking at the same time get two different numbers. *template* reserves
    ``w000`` (refused when it already exists). *ext* = scene extension (default: the one
    of *license*). Returns the manifest + target paths (``hip``)."""
    folder = Path(folder)
    ext = (ext or hip_ext_for_license(license)).lower()
    if ext not in HIP_EXTS:
        raise WorkError(f"Extension de scene invalide : {ext!r}")
    folder.mkdir(parents=True, exist_ok=True)
    taken = [_number(v["version"]) for v in list_versions(folder)]
    number = 0 if template else max([n for n in taken if n > 0] + [0]) + 1
    manifest = {
        "state": STATE_WRITING, "based_on": based_on or "", "author": author or "",
        "host": host or socket.gethostname(), "date": _now(), "comment": comment or "",
        "houdini_version": houdini_version or "", "license": license or "",
        "category": category or "", "project": project or "", "seq": seq, "shot": shot,
        "task": task,
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
            "hip": str(folder / (version + ext)).replace("\\", "/"),
            "manifest": str(path).replace("\\", "/")}


def commit_version(folder: str | Path, version: str, *, size: int = 0,
                   node_types: list | None = None, external_deps: list | None = None,
                   embedded_hdas: list | None = None, render_blocks: list | None = None) -> dict:
    """Mark a reservation ``ok`` once Houdini has written the scene. No content hash: two
    identical saves of a .hip differ (ADR 0090), the scene's own dirty flag replaces it."""
    folder = Path(folder)
    _number(version)
    path = folder / (version + ".json")
    manifest = _read_json(path)
    if manifest is None:
        raise WorkError(f"Version inconnue : {version}")
    if manifest.get("state") != STATE_WRITING:
        raise WorkError(f"{version} n'est pas en cours d'ecriture (etat {manifest.get('state')})")
    hip = _first_hip(folder, version)
    if hip is None:
        raise WorkError(f"Scene {version} absente : la sauvegarde Houdini n'a pas abouti")
    manifest.update({
        "state": STATE_OK, "size": size or hip.stat().st_size, "file": hip.name,
        "node_types": node_types or [], "external_deps": external_deps or [],
        "embedded_hdas": embedded_hdas or [], "committed": _now(),
    })
    if render_blocks is not None:
        manifest["render_blocks"] = render_blocks
    _write_json(path, manifest)
    return {**manifest, "version": version, "hip": str(hip).replace("\\", "/")}


def abort_version(folder: str | Path, version: str) -> bool:
    """Drop a reservation whose save failed (manifest + leftovers). An ``ok`` version
    is never removed."""
    folder = Path(folder)
    _number(version)
    path = folder / (version + ".json")
    manifest = _read_json(path)
    if manifest is None or manifest.get("state") == STATE_OK:
        return False
    for leftover in [folder / (version + ext) for ext in HIP_EXTS] + [path]:
        try:
            leftover.unlink()
        except FileNotFoundError:
            pass
    return True


def start_work(folder: str | Path, project_path: str | Path, *, project: str, seq: str,
               shot: str, task: str, author: str = "", host: str = "") -> dict:
    """What to open for a task: its newest committed scene. A task without any version
    gets its template copied into ``w000`` first (never over an existing file); Houdini
    then opens w000, sets the task and saves w001 right away (ADR 0090 point 4)."""
    folder = Path(folder)
    latest = latest_ok(folder)
    created = False
    if latest is None:
        source, origin = template_hip(project_path, task)
        if source is None:
            raise WorkError(f"Aucun template Houdini pour la tache {task}")
        reserved = reserve_version(folder, author=author, host=host, comment="template",
                                   category=TASK_CATEGORY.get(task.upper(), ""), project=project,
                                   seq=seq, shot=shot, task=task, ext=source.suffix, template=True)
        target = Path(reserved["hip"])
        try:
            with open(source, "rb") as src, open(target, "xb") as dst:
                shutil.copyfileobj(src, dst)
        except OSError as exc:
            abort_version(folder, "w000")
            raise WorkError(f"Copie du template impossible : {exc}") from exc
        commit_version(folder, "w000")
        created = True
        log.info("Work template copied: %s -> %s (%s)", source, target, origin)
        latest = latest_ok(folder)
    return {"hip": latest["hip"], "version": latest["version"], "created_template": created,
            "folder": str(folder).replace("\\", "/")}


def identify(path: str | Path) -> dict | None:
    """Task of an opened scene ``.../wNNN.<hip ext>`` from its manifest; None when the
    file is not a FLUX Work version (a free scene)."""
    path = Path(path)
    if path.suffix.lower() not in HIP_EXTS or not re.match(r"^w\d{3,}$", path.stem):
        return None
    manifest = _read_json(path.with_suffix(".json"))
    if not manifest or not manifest.get("task"):
        return None
    return {"project": manifest.get("project", ""), "seq": manifest.get("seq", ""),
            "shot": manifest.get("shot", ""), "task": manifest.get("task", ""),
            "version": path.stem, "state": manifest.get("state", ""),
            "category": manifest.get("category", ""),
            "folder": str(path.parent).replace("\\", "/")}


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

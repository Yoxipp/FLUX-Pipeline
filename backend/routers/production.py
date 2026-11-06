# routers/production.py — Production Tab endpoints.
#
# GET  /production/{project}                  read + reconcile against activite.json
# PUT  /production/{project}                  replace production.json (debounced by front)
# POST /production/{project}/materialize      create the disk folder for an entity

from __future__ import annotations

import asyncio
import mimetypes
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel

from core import config
from core.constants import DEFAULT_TYPE_TOKENS, JSON_MODIF_LOG
from core.executors import HEAVY
from core.logger import get_logger
from core.paths import get_project_path
from features.accounts.alias_views import alias_etag, resolve_production_doc
from features.activity.activity_reader import get_all_events
from features.activity.activity_writer import log_event
from features.folder_manager.tokens import load_tokens, remove_token
from features.folder_manager.naming_validator import get_base_name
from core.constants import DEFAULT_CLASS_TOKENS
from features.production import archive as prod_archive
from features.production import lock as prod_lock
from features.production import production_store as store
from features.production import scan_cache
from features.production import montage_export, ref_media
from features.production.disk_scan import scan_project_assets, scan_project_shots
from features.production.reconcile import reconcile
from features.production.sync import sync_production_to_disk
from features.publisher.modif_log import read_logs
from routers.activity import _not_modified
from utils import project_utils

log = get_logger(__name__)
router = APIRouter()


class ProductionPayload(BaseModel):
    production: dict


class CommentNotify(BaseModel):
    class_token: str
    name:        str
    task:        str
    subtask:     str | None = None
    text:        str | None = None


def _ensure_project(project: str) -> None:
    if not project_utils.project_exists(project):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")


def _require_role(project: str, action: str) -> None:
    """403 when the active user's project role is too low (ADR 0064)."""
    from features.roles import project_roles

    try:
        project_roles.require(project, action)
    except project_roles.RoleError as exc:
        raise HTTPException(status_code=403, detail=str(exc))


# In-process cache of parsed modif_logs.json, keyed by folder path → (mtime,
# logs). A modif log is only re-read from disk when its mtime changes (i.e. a
# new publish landed), so repeated production GETs cost a cheap stat() instead
# of an open+parse per folder. Survives across requests for the process life.
_MODIF_LOG_CACHE: dict[str, tuple[float, list[dict]]] = {}


def _cached_modif_logs(folder) -> list[dict]:
    """Return a folder's modif-log entries (newest first), cached by mtime."""
    try:
        mtime = (folder / JSON_MODIF_LOG).stat().st_mtime
    except OSError:
        return []                                  # no modif log in this folder
    key = str(folder).lower()
    hit = _MODIF_LOG_CACHE.get(key)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    logs = read_logs(folder)
    _MODIF_LOG_CACHE[key] = (mtime, logs)
    return logs


_VERSION_IN_FILE = re.compile(r"_(v\d{3,})(?=\.|$)")


def _attach_publish_comments(project_path, publishes_by_task: dict) -> None:
    """Attach each publish's modif-log comment as event['description'] (in place).

    The comment (the publish description) lives in modif_logs.json inside the
    shared publish folder. An event's dest_folder may point at that folder or at
    a ``<base>_<FMT>_LAST`` child, so we search the folder and up to two parents,
    matching by base name and preferring the entry whose timestamp equals the
    event's. Reads go through the mtime cache so disk is touched only on change.
    Best-effort — any failure just leaves description unset.
    """
    flux_prefix = "$FLUX/"

    def rel_for(ev: dict):
        dest = (ev.get("dest_folder") or "").replace("\\", "/")
        if not dest:
            return None
        if dest.startswith(flux_prefix):
            dest = dest[len(flux_prefix):]
        parts = dest.split("/")
        if len(parts) >= 2 and parts[0].lower() == "dossier_projets":
            parts = parts[2:]                      # drop DOSSIER_PROJETS/<project>
        inside = "/".join(parts).strip("/")
        return inside or None

    for bucket in publishes_by_task.values():
        for ev in bucket:
            rel = rel_for(ev)
            fname = ev.get("file") or ""
            if not rel or not fname:
                continue
            base = get_base_name(fname)
            if not base:
                continue
            folder = project_path / rel
            for cand in (folder, folder.parent, folder.parent.parent):
                logs = [e for e in _cached_modif_logs(cand)
                        if str(e.get("name", "")) == base or str(e.get("name", "")).startswith(base + "_")]
                if not logs:
                    continue
                # The version in the file name is the reliable key: the log and the
                # event are timestamped separately and can straddle a minute.
                ver = _VERSION_IN_FILE.search(fname)
                exact = next((e for e in logs if ver and e.get("version") == ver.group(1)), None) or \
                    next((e for e in logs
                          if e.get("date") == ev.get("date") and e.get("time") == ev.get("time")), None)
                # No match: leave it unset rather than borrow another version's note.
                desc = ((exact or {}).get("modification", "") if ver else (exact or logs[0]).get("modification", "")) or ""
                if desc:
                    ev["description"] = desc
                break


@router.get("/{project}")
async def get_production(project: str, request: Request):
    """Load production.json + reconcile against publish events.

    Auto-created entities (from reconcile) are persisted before returning so
    later edits (renaming a task's label, etc.) survive.

    Served through scan_cache (single-flight + 1 s TTL, dropped on any local
    write) and answered 304 when the client's ETag still matches.
    """
    _ensure_project(project)
    try:
        result, etag = await scan_cache.get(project, lambda: _compute_production(project))
    except RuntimeError as e:
        # FLUX_ROOT not yet configured — return an empty shell rather than a 500.
        log.warning("Production read fallback: %s", e)
        return {
            "production": store.default_schema(),
            "publishes_by_task": {},
            "publishes_unmatched": [],
            "sequences_on_disk": [],
            "shots_on_disk": [],
        }
    # A rename changes the shown names without touching production.json.
    etag = alias_etag(etag)
    if _not_modified(request, etag):
        return Response(status_code=304, headers={"ETag": etag})
    # Renamed artists: resolve on a copy (result is shared by scan_cache, never mutate it).
    shown = {**result, "production": resolve_production_doc(result.get("production"))}
    return JSONResponse(shown, headers={"ETag": etag})


async def _compute_production(project: str) -> dict:
    """The full production read (disk scan + reconcile), run in a worker thread."""
    loop = asyncio.get_running_loop()
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        production = store.load_production(project)
        # Snapshot the state we would persist, to skip a disk write when nothing changed.
        before = _fingerprint(production)
        try:
            events = get_all_events(limit=10_000, action="publish", project=project)
        except RuntimeError:
            events = []
        # Known TYPE tokens (defaults + project custom entries) — used by the
        # old-vs-new nomenclature disambiguator in reconcile.
        try:
            project_tokens = load_tokens(get_project_path(project))
            type_map  = project_tokens.get("TYPE")  or {}
            class_map = project_tokens.get("CLASS") or {}
        except Exception:
            type_map, class_map = {}, {}
        merged_type_map  = {**DEFAULT_TYPE_TOKENS,  **type_map}
        merged_class_map = {**DEFAULT_CLASS_TOKENS, **class_map}
        known_type_tokens = {k.upper() for k in merged_type_map.keys()}

        # Disk-scan: surface assets scaffolded outside Production Tab so tasks
        # with a non-empty folder + instance subdirs appear even before any
        # publish exists.
        try:
            disk_assets = scan_project_assets(get_project_path(project), merged_class_map, merged_type_map)
        except Exception as e:
            log.warning("disk_scan (assets) failed: %s", e)
            disk_assets = []
        try:
            disk_shots = scan_project_shots(get_project_path(project), merged_class_map)
        except Exception as e:
            log.warning("disk_scan (shots) failed: %s", e)
            disk_shots = []

        production, publishes_by_task, unmatched = reconcile(
            production, events, known_type_tokens, disk_assets, disk_shots,
        )
        # Disk → logical: drop AUTO entities whose folder was deleted on disk.
        # User-planned entities are never auto-pruned (guards against OneDrive/AV
        # hiccups); they are removed explicitly from the Publisher instead.
        try:
            prod_archive.prune_absent_auto(get_project_path(project), production)
        except Exception as e:
            log.warning("prune_absent_auto failed: %s", e)
        try:
            _attach_publish_comments(get_project_path(project), publishes_by_task)
        except Exception as e:
            log.warning("attach_publish_comments failed: %s", e)
        after = _fingerprint(production)
        if after != before:
            store.save_production(project, production)
        seqs_on_disk = sorted({(d.get("seq") or "").upper() for d in disk_shots if d.get("seq")})
        shots_on_disk = sorted({((d.get("seq") or "").upper(), (d.get("shot") or "").upper())
                                for d in disk_shots
                                if d.get("seq") and d.get("shot")})
        return {
            "production": production,
            "publishes_by_task": publishes_by_task,
            "publishes_unmatched": unmatched,
            "sequences_on_disk": seqs_on_disk,
            "shots_on_disk": [list(x) for x in shots_on_disk],
        }

    return await loop.run_in_executor(HEAVY, _do)



def _shot_keys(production: dict) -> dict[tuple[str, str], tuple]:
    """(SEQ, SHOT) -> what the shot stage reads from Production (casting with its pinned
    versions, ADR 0048, + frame range)."""
    from features.usd_assembler.shot_stage import read_casting, read_frame_range

    seqs = {s.get("id"): s.get("name") for s in production.get("sequences", [])}
    out = {}
    for sh in production.get("shots", []):
        seq = seqs.get(sh.get("seq_id"))
        if seq and sh.get("name"):
            cast = sorted((c["name"], c["count"], c.get("version") or "")
                          for c in read_casting(production, seq, sh["name"]))
            out[(seq, sh["name"])] = (tuple(cast), read_frame_range(production, seq, sh["name"]))
    return out


def _refresh_changed_shot_stages(project: str, before: dict, after: dict,
                                 changed: list | None = None) -> list[str]:
    """Regenerate the stage of every shot whose casting or range changed. Returns the
    ``SEQ_SHOT vNNN`` written; *changed* (optional) receives their (seq, shot)."""
    from features.usd_assembler.shot_stage import stage_versions, write_stage

    old, new = _shot_keys(before or {}), _shot_keys(after or {})
    written = []
    project_path = get_project_path(project)
    for key, value in new.items():
        # Every shot has its stage (2026-09-19): a shot without one gets it now.
        if old.get(key) == value and stage_versions(project_path, key[0], key[1]):
            continue
        res = write_stage(get_project_path(project), key[0], key[1], production=after,
                          save_casting=False)
        if res.get("version"):
            written.append(f"{key[0]}_{key[1]} {res['version']}")
            if changed is not None:
                changed.append(key)
    return written

@router.put("/{project}")
async def put_production(project: str, payload: ProductionPayload) -> dict:
    """Replace production.json with *payload.production* (atomic), then mirror the
    planning to disk.

    The disk mirror is the Production → Disk half of the bidirectional sync: every
    asset / sequence / shot / task / subtask declared in production.json is ensured
    to exist on disk. It is strictly CREATE-ONLY (see features/production/sync.py):
    a save can add missing folders but can never delete, move or overwrite existing
    files. A sync failure never fails the save — the planning is persisted first.
    """
    _ensure_project(project)
    loop = asyncio.get_running_loop()
    previous = await loop.run_in_executor(None, lambda: store.load_production(project))
    # A stale client (other window / machine) must not bring back a deleted seq / shot.
    prod_archive.keep_archived_out(payload.production, previous)
    # Locked seq / shot records come back as stored (2026-09-30).
    locked_kept = prod_lock.keep_locked(payload.production, previous)
    # A junior changes task progress, not the seq / shot records (2026-10-24).
    from features.roles import project_roles
    if not project_roles.can(project, "edit_entity"):
        locked_kept += prod_lock.keep_all_records(payload.production, previous)
    ok = await loop.run_in_executor(None, lambda: store.save_production(project, payload.production))
    if not ok:
        raise HTTPException(status_code=500, detail="Écriture production.json échouée")
    # Phone notify (ADR 0062): a new assignee or retake, seen as a diff of the saved doc.
    try:
        from features.notify import hooks as notify_hooks
        notify_hooks.on_production(project, previous, payload.production, config.get_current_user() or "")
    except Exception as e:  # noqa: BLE001 — the save already succeeded
        log.warning("Notify after Production save skipped for %r: %s", project, e)

    # A4 (ADR 0020): a casting or frame range edit regenerates that shot's stage.
    stages: list[str] = []
    changed_shots: list = []
    try:
        stages = await loop.run_in_executor(
            None, lambda: _refresh_changed_shot_stages(project, previous, payload.production,
                                                       changed_shots))
    except Exception as e:  # noqa: BLE001 — the save already succeeded
        log.warning("Shot stage refresh after Production save failed for %r: %s", project, e)
    # P0 Houdini Work: an open Houdini follows the new stages (range + layer reload).
    try:
        from dcc.houdini.shot_sync import notify_shot_stages_async
        notify_shot_stages_async(project, changed_shots)
    except Exception as e:  # noqa: BLE001 — best effort
        log.warning("Houdini shot stage sync failed for %r: %s", project, e)

    synced = {}
    try:
        synced = await loop.run_in_executor(
            None, lambda: sync_production_to_disk(get_project_path(project), payload.production)
        )
    except Exception as e:  # noqa: BLE001 — sync is best-effort, save already succeeded
        log.warning("Production→disk sync failed for %r: %s", project, e)

    return {"success": True, "synced": synced, "shot_stages": stages, "locked_kept": locked_kept}


@router.post("/{project}/comment")
async def notify_comment(project: str, payload: CommentNotify) -> dict:
    """Emit an activity event when a comment is posted.

    Persistence of the comment itself lives in production.json (frontend writes
    it there via the normal debounced PUT). This endpoint only fans out the
    notification so favorited-task subscribers can see it in Activity.
    """
    _ensure_project(project)
    user = config.get_current_user() or "unknown"
    # Build a filename token string so the client's Fav filter can parse it
    # with the same rules as a publish event.
    parts = [payload.class_token.upper(), payload.name.upper(), payload.task.upper()]
    if payload.subtask:
        parts.append(payload.subtask.upper())
    filename = "_".join(parts)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(
        None,
        lambda: log_event(user, "comment", project, filename=filename, dest_folder=None),
    )
    return {"success": True}


class ShotRetake(BaseModel):
    seq:  str
    shot: str
    task: str
    text: str


@router.post("/{project}/retake")
async def add_shot_retake(project: str, payload: ShotRetake) -> dict:
    """Add one 'retake' comment to a shot task (ADR 0083: an idea of the board shotboard
    sent to Production). Read, append, save in one step on the backend: the board never
    PUTs the whole production.json. A locked shot still takes it (task progress stays
    editable on a locked record, features/production/lock.py)."""
    _ensure_project(project)
    user = config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        import copy
        from datetime import datetime
        production = store.load_production(project)
        previous = copy.deepcopy(production)
        now = datetime.now()
        comment = store.add_shot_retake_comment(production, payload.seq, payload.shot, payload.task,
                                                payload.text, user, now.strftime("%Y-%m-%d"), now.strftime("%H:%M"))
        if not store.save_production(project, production):
            raise RuntimeError("Écriture production.json échouée")
        return {"previous": previous, "production": production, "comment": comment}

    try:
        res = await loop.run_in_executor(None, _do)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.exception("shot retake failed")
        raise HTTPException(status_code=500, detail=str(e))
    # Same side effects as a retake typed in the task panel: phone notify, Activity event.
    try:
        from features.notify import hooks as notify_hooks
        notify_hooks.on_production(project, res["previous"], res["production"], user)
    except Exception as e:  # noqa: BLE001 — the retake is saved
        log.warning("Notify after board retake skipped for %r: %s", project, e)
    try:
        filename = "_".join([payload.seq.upper(), payload.shot.upper(), payload.task.upper()])
        await loop.run_in_executor(None, lambda: log_event(user, "comment", project, filename=filename, dest_folder=None))
    except Exception as e:  # noqa: BLE001
        log.warning("Activity event after board retake skipped for %r: %s", project, e)
    return {"ok": True, "comment": res["comment"]}


# ── Delete = archive (never hard-delete) ──────────────────────────────────────

class ArchiveRequest(BaseModel):
    rel_path: str


@router.get("/{project}/entity-folder")
async def entity_folder(
    project: str,
    kind: str = "asset",
    class_token: str = "",
    name: str = "",
    seq: str = "",
    shot: str = "",
    count: bool = True,
) -> dict:
    """Resolve a Production entity's on-disk folder and report existence + file
    count, so the UI can warn before archiving (prevention message).
    count=false skips the file count (open in the Folder Manager)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        rel = prod_archive.resolve_entity_rel(project_path, kind, class_token, name, seq, shot)
        if rel is None:
            return {"rel_path": "", "exists": False, "file_count": 0}
        return prod_archive.inspect_folder(project_path, rel, count=count)

    return await loop.run_in_executor(None, _do)


@router.post("/{project}/archive")
async def archive_entity(project: str, payload: ArchiveRequest) -> dict:
    """Move an entity folder into <project>/ARCHIVE/<timestamp>/. The frontend
    removes the logical entity from production.json AFTER this succeeds."""
    _ensure_project(project)
    _require_role(project, "edit_entity")
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        archived = await loop.run_in_executor(
            None, lambda: prod_archive.archive_folder(project_path, payload.rel_path)
        )
    except FileNotFoundError:
        # Nothing on disk to archive — treat as success so the caller can still
        # drop the (ghost) logical entity.
        return {"archived": False, "reason": "not_found"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("archive failed")
        raise HTTPException(status_code=500, detail=str(e))
    try:
        dropped = await loop.run_in_executor(
            None, lambda: prod_archive.drop_tokens_under(project_path, payload.rel_path)
        )
    except Exception as e:  # noqa: BLE001 - the folder is archived, tokens are secondary
        log.warning("drop_tokens_under %s failed: %s", payload.rel_path, e)
        dropped = []
    return {"archived": True, "archived_to": archived, "tokens_dropped": dropped}


class DeleteSeqShotRequest(BaseModel):
    kind: str            # 'seq' | 'shot'
    seq:  str
    shot: str = ""


@router.post("/{project}/delete-seq-shot")
async def delete_seq_shot(project: str, payload: DeleteSeqShotRequest) -> dict:
    """Delete a sequence / shot: archive its folders (shot tree + comp / lighting), drop
    its tokens and remove it from production.json in one go, with a tombstone so neither
    an old publish nor a stale save brings it back."""
    _ensure_project(project)
    _require_role(project, "edit_entity")
    if payload.kind not in ("seq", "shot"):
        raise HTTPException(status_code=400, detail=f"kind invalide : {payload.kind!r}")
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        production = store.load_production(project)
        prod_lock.ensure_unlocked(production, payload.kind, payload.seq, payload.shot)
        res = prod_archive.delete_seq_shot(project_path, production, payload.kind, payload.seq, payload.shot)
        if not store.save_production(project, production):
            raise RuntimeError("Écriture production.json échouée")
        return res

    try:
        res = await loop.run_in_executor(None, _do)
    except prod_lock.LockedError as e:
        raise HTTPException(status_code=423, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("delete-seq-shot failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, **res}


class RenameSeqShotRequest(BaseModel):
    kind: str            # 'seq' | 'shot'
    seq:  str
    shot: str = ""
    new:  str            # SEQnnn / SHOTnnn


@router.post("/{project}/rename-seq-shot")
async def rename_seq_shot(project: str, payload: RenameSeqShotRequest) -> dict:
    """Rename a sequence / shot in production.json AND on disk. Refused (409) while it
    holds artist files: publishes carry the name in their files and USD paths."""
    from features.production import rename as prod_rename

    _ensure_project(project)
    _require_role(project, "edit_entity")
    if payload.kind not in ("seq", "shot"):
        raise HTTPException(status_code=400, detail=f"kind invalide : {payload.kind!r}")
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        prod_lock.ensure_unlocked(store.load_production(project), payload.kind, payload.seq, payload.shot)
        found = prod_rename.blockers(project_path, payload.kind, payload.seq, payload.shot)
        if found:
            shown = ", ".join(found[:4]) + (f" (+{len(found) - 4})" if len(found) > 4 else "")
            raise PermissionError(f"{len(found)} fichier(s) publie(s) : renommer casserait leurs noms et "
                                  f"leurs chemins USD. Cree plutot un nouveau shot. {shown}")
        production = store.load_production(project)
        prod_rename.rename_in_production(production, payload.kind, payload.seq, payload.shot, payload.new)
        # Saved first: the new shot stage reads its casting / range from production.json.
        if not store.save_production(project, production):
            raise RuntimeError("Écriture production.json échouée")
        return prod_rename.rename_on_disk(project_path, payload.kind, payload.seq, payload.shot, payload.new)

    try:
        res = await loop.run_in_executor(None, _do)
    except prod_lock.LockedError as e:
        raise HTTPException(status_code=423, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("rename-seq-shot failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, **res}


class LockSeqShotRequest(BaseModel):
    kind:   str          # 'seq' | 'shot'
    seq:    str
    shot:   str = ""
    locked: bool
    phrase: str = ""     # "Understand" to unlock


@router.post("/{project}/lock")
async def lock_seq_shot(project: str, payload: LockSeqShotRequest) -> dict:
    """Lock / unlock a sequence or shot (2026-09-30). Anyone can; unlocking needs the
    phrase. A lock blocks editing, renaming and deleting the record."""
    _ensure_project(project)
    if payload.kind not in ("seq", "shot"):
        raise HTTPException(status_code=400, detail=f"kind invalide : {payload.kind!r}")
    user = config.get_current_user() or "unknown"
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        production = store.load_production(project)
        entity = prod_lock.set_lock(production, payload.kind, payload.seq, payload.shot,
                                    payload.locked, user, payload.phrase)
        if not store.save_production(project, production):
            raise RuntimeError("Écriture production.json échouée")
        return {"locked": entity.get(prod_lock.LOCK_KEY)}

    try:
        res = await loop.run_in_executor(None, _do)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        log.exception("lock-seq-shot failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, **res}


# ── Composer token archive (Publisher ghost-token cross) ──────────────────────

class ArchiveTokenRequest(BaseModel):
    field:       str                 # 'name' | 'instance' | 'seq' | 'shot'
    class_token: str = ""
    name:        str = ""
    task:        str = ""
    instance:    str = ""
    seq:         str = ""
    shot:        str = ""


def _resolve_token_rel(project_path, req_like) -> tuple[str | None, tuple[str, str] | None]:
    """Return (project-relative folder, (token_section, token_value)) for a
    composer token, or (None, None) when the field is unsupported.

    The token tuple is what to drop from tokens.json after archiving (or None
    when the field maps to no persisted token entry)."""
    field = (getattr(req_like, "field", "") or "").lower()
    cls   = getattr(req_like, "class_token", "") or ""
    name  = getattr(req_like, "name", "") or ""
    task  = getattr(req_like, "task", "") or ""
    inst  = getattr(req_like, "instance", "") or ""
    seq   = getattr(req_like, "seq", "") or ""
    shot  = getattr(req_like, "shot", "") or ""

    if field == "name":
        rel = ref_media.resolve_ref_root(project_path, "asset", class_token=cls, name=name)
        return rel or None, ("NAME", name.upper())
    if field == "instance":
        rel = ref_media.resolve_ref_root(project_path, "asset", class_token=cls, name=name, task=task, subtask=inst)
        return rel or None, ("INSTANCE", inst.lower())
    if field == "seq":
        return prod_archive.resolve_entity_rel(project_path, "seq", seq=seq), ("SEQ", seq.upper())
    if field == "shot":
        rel = prod_archive.resolve_entity_rel(project_path, "shot", seq=seq, shot=shot)
        return rel, ("SHOT", f"{seq.upper()}/{shot.upper()}")
    return None, None


@router.get("/{project}/token-folder")
async def token_folder(
    project: str,
    field: str = "name",
    class_token: str = "",
    name: str = "",
    task: str = "",
    instance: str = "",
    seq: str = "",
    shot: str = "",
) -> dict:
    """Resolve a composer token's on-disk folder + file count, to warn before
    archiving the token from the Publisher."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()

    class _R:
        pass
    r = _R()
    r.field, r.class_token, r.name = field, class_token, name
    r.task, r.instance, r.seq, r.shot = task, instance, seq, shot

    def _do() -> dict:
        rel, _tok = _resolve_token_rel(project_path, r)
        if not rel:
            return {"rel_path": "", "exists": False, "file_count": 0}
        return prod_archive.inspect_folder(project_path, rel)

    return await loop.run_in_executor(None, _do)


@router.post("/{project}/archive-token")
async def archive_token(project: str, payload: ArchiveTokenRequest) -> dict:
    """Archive a composer token's folder (into ARCHIVE/) and drop the token from
    tokens.json. Never hard-deletes — mirrors the entity archive flow."""
    _ensure_project(project)
    _require_role(project, "edit_entity")
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()

    def _do() -> dict:
        rel, tok = _resolve_token_rel(project_path, payload)
        if not rel:
            raise HTTPException(status_code=400, detail=f"Token non résolu : {payload.field!r}")
        archived_to = None
        try:
            archived_to = prod_archive.archive_folder(project_path, rel)
        except FileNotFoundError:
            pass  # ghost with no folder — still drop the token below
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        if tok is not None:
            try:
                remove_token(project_path, tok[0], tok[1])
            except Exception as e:  # noqa: BLE001 — token removal is best-effort
                log.warning("remove_token %s/%s failed: %s", tok[0], tok[1], e)
        return {"archived": archived_to is not None, "archived_to": archived_to}

    try:
        return await loop.run_in_executor(None, _do)
    except HTTPException:
        raise
    except Exception as e:
        log.exception("archive_token failed")
        raise HTTPException(status_code=500, detail=str(e))


# NOTE: the old POST /{project}/materialize endpoint (manual "Create on Disk")
# was removed. Disk structure is now created automatically and bidirectionally:
#   * Production → Disk : PUT /{project} mirrors the planning to disk (create-only,
#     see features/production/sync.py).
#   * Disk → Production : GET /{project} adopts on-disk assets/shots via disk_scan.


# ── Reference media (/ref embed zone) ─────────────────────────────────────────

class RefExport(BaseModel):
    rel_path: str = ""
    name: str            # LAST.<ext> or vNNN.<ext>
    dest_path: str       # absolute path chosen via the OS save dialog


@router.get("/{project}/ref/resolve")
async def resolve_ref(
    project: str,
    kind: str = "asset",
    class_token: str = "",
    name: str = "",
    seq: str = "",
    shot: str = "",
    task: str = "",
    subtask: str = "",
) -> dict:
    """Resolve the project-relative root of a task/subtask (where /ref lives)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    rel = await loop.run_in_executor(
        None,
        lambda: ref_media.resolve_ref_root(
            project_path, kind, class_token, name, seq, shot, task, subtask,
        ),
    )
    return {"rel_path": rel}


@router.post("/{project}/ref")
async def deposit_ref(project: str, request: Request, rel_path: str = "", filename: str = "") -> dict:
    """Store a dropped image/video as the next version and refresh LAST.

    The body is the raw file bytes (the renderer POSTs the File directly);
    `rel_path` is the project-relative root of the task/subtask.
    """
    _ensure_project(project)
    data = await request.body()
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: ref_media.deposit(
                project_path, rel_path, filename, data, config.get_current_user() or "",
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("ref deposit failed")
        raise HTTPException(status_code=500, detail=str(e))
    return result


@router.get("/{project}/ref/latest")
async def latest_ref(project: str, rel_path: str = "") -> dict:
    """Return info about the current LAST file, or {found: false} when empty."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        info = await loop.run_in_executor(
            None, lambda: ref_media.latest(project_path, rel_path)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not info:
        return {"found": False}
    return {"found": True, **info}


@router.get("/{project}/ref/versions")
async def ref_versions(project: str, rel_path: str = "") -> dict:
    """Every version of a /ref zone, newest first, from its modif log (retake 10)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        rows = await loop.run_in_executor(None, lambda: ref_media.versions(project_path, rel_path))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"versions": rows}


class ShotPreviewQuery(BaseModel):
    seq: str
    shot: str
    tasks: list[str] = []


class ShotPreviewsRequest(BaseModel):
    shots: list[ShotPreviewQuery]


@router.post("/{project}/shot-previews")
async def shot_previews(project: str, payload: ShotPreviewsRequest) -> dict:
    """LAST media of each task of the given shots (Timeline preview, auto edit)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()

    def _do() -> list[dict]:
        return [
            {"seq": q.seq, "shot": q.shot,
             "media": ref_media.shot_previews(project_path, q.seq, q.shot, q.tasks)}
            for q in payload.shots
        ]

    return {"shots": await loop.run_in_executor(None, _do)}


class MontageClipIn(BaseModel):
    seq: str = ""
    shot: str = ""
    frames: int = 1
    media: dict | None = None        # {task, label, rel_path, file, source} as shot-previews gave it


class MontageExportRequest(BaseModel):
    name: str = "montage"
    dest_dir: str
    fps: float = 24
    mov: bool = True
    folder: bool = True
    clips: list[MontageClipIn]


@router.post("/{project}/montage/export")
async def export_montage(project: str, payload: MontageExportRequest) -> dict:
    """Export the Timeline auto edit: media + .otio + .edl and/or one H.264 .mov."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, lambda: montage_export.export_montage(
            project_path, [c.model_dump() for c in payload.clips], payload.fps,
            payload.dest_dir, payload.name, payload.mov, payload.folder))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{project}/ref/file")
async def stream_ref(project: str, rel_path: str = "", name: str = "", scope: str = "ref") -> FileResponse:
    """Stream a ref file (Range-enabled by FileResponse) for the <img>/<video> src.

    scope="publish": a published image/video (`*_LAST.ext`) in the folder
    `rel_path` itself (Timeline preview fallback), not in its /ref zone.
    """
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    resolver = ref_media.resolve_publish_file if scope == "publish" else ref_media.resolve_file
    try:
        path = await loop.run_in_executor(
            None, lambda: resolver(project_path, rel_path, name)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


class RefFileOp(BaseModel):
    rel_path: str = ""
    name: str            # vNNN.<ext>


@router.post("/{project}/ref/delete")
async def delete_ref_version(project: str, payload: RefFileOp) -> dict:
    """Delete one version of a /ref zone; LAST is re-pointed to the newest remaining one."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, lambda: ref_media.delete_version(project_path, payload.rel_path, payload.name))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable")


@router.post("/{project}/ref/restore")
async def restore_ref_version(project: str, payload: RefFileOp) -> dict:
    """Set an older version as LAST (re-deposited as the next version)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(
            None, lambda: ref_media.restore_version(
                project_path, payload.rel_path, payload.name, config.get_current_user() or ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable")


@router.post("/{project}/ref/export")
async def export_ref(project: str, payload: RefExport) -> dict:
    """Copy a ref file to a user-chosen destination (download button)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_running_loop()
    try:
        dest = await loop.run_in_executor(
            None, lambda: ref_media.export_to(project_path, payload.rel_path, payload.name, payload.dest_path)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    except Exception as e:
        log.exception("ref export failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"ok": True, "dest": str(dest)}


# ── helpers ──────────────────────────────────────────────────────────────────

def _fingerprint(production: dict) -> tuple[Any, ...]:
    """Cheap change-detection: len + concatenation of ids that reconcile can add.

    We use it to skip a disk write when reconcile did not add/mutate anything.
    """
    asset_ids = tuple(a.get("id") for a in production.get("assets", []))
    task_sigs = tuple(
        (a.get("id"), t.get("id"), tuple(t.get("known_subtasks", [])), tuple(t.get("type_tokens", [])))
        for a in production.get("assets", [])
        for t in a.get("tasks", [])
    )
    seq_ids  = tuple(s.get("id") for s in production.get("sequences", []))
    shot_ids = tuple((s.get("seq_id"), s.get("id")) for s in production.get("shots", []))
    shot_task_sigs = tuple(
        (s.get("id"), t.get("id"), tuple(t.get("known_subtasks", [])), tuple(t.get("type_tokens", [])))
        for s in production.get("shots", [])
        for t in s.get("tasks", [])
    )
    return (asset_ids, task_sigs, seq_ids, shot_ids, shot_task_sigs)

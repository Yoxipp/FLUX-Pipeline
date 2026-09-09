# routers/production.py — Production Tab endpoints.
#
# GET  /production/{project}                  read + reconcile against activite.json
# PUT  /production/{project}                  replace production.json (debounced by front)
# POST /production/{project}/materialize      create the disk folder for an entity

from __future__ import annotations

import asyncio
import mimetypes
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core import config
from core.constants import DEFAULT_TYPE_TOKENS, JSON_MODIF_LOG
from core.logger import get_logger
from core.paths import get_project_path
from features.activity.activity_reader import get_all_events
from features.activity.activity_writer import log_event
from features.folder_manager.tokens import load_tokens
from features.folder_manager.naming_validator import get_base_name
from core.constants import DEFAULT_CLASS_TOKENS
from features.production import production_store as store
from features.production import ref_media
from features.production.disk_scan import scan_project_assets, scan_project_shots
from features.production.reconcile import reconcile
from features.production.sync import sync_production_to_disk
from features.publisher.modif_log import read_logs
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
                logs = [e for e in _cached_modif_logs(cand) if str(e.get("name", "")).startswith(base)]
                if not logs:
                    continue
                exact = next((e for e in logs
                              if e.get("date") == ev.get("date") and e.get("time") == ev.get("time")), None)
                desc = (exact or logs[0]).get("modification", "") or ""
                if desc:
                    ev["description"] = desc
                break


@router.get("/{project}")
async def get_production(project: str) -> dict:
    """Load production.json + reconcile against publish events.

    Auto-created entities (from reconcile) are persisted before returning so
    later edits (renaming a task's label, etc.) survive.
    """
    _ensure_project(project)
    loop = asyncio.get_event_loop()

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

    try:
        return await loop.run_in_executor(None, _do)
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
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: store.save_production(project, payload.production))
    if not ok:
        raise HTTPException(status_code=500, detail="Écriture production.json échouée")

    synced = {}
    try:
        synced = await loop.run_in_executor(
            None, lambda: sync_production_to_disk(get_project_path(project), payload.production)
        )
    except Exception as e:  # noqa: BLE001 — sync is best-effort, save already succeeded
        log.warning("Production→disk sync failed for %r: %s", project, e)

    return {"success": True, "synced": synced}


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
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        lambda: log_event(user, "comment", project, filename=filename, dest_folder=None),
    )
    return {"success": True}


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
    loop = asyncio.get_event_loop()
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
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            None, lambda: ref_media.deposit(project_path, rel_path, filename, data)
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
    loop = asyncio.get_event_loop()
    try:
        info = await loop.run_in_executor(
            None, lambda: ref_media.latest(project_path, rel_path)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not info:
        return {"found": False}
    return {"found": True, **info}


@router.get("/{project}/ref/file")
async def stream_ref(project: str, rel_path: str = "", name: str = "") -> FileResponse:
    """Stream a ref file (Range-enabled by FileResponse) for the <img>/<video> src."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_event_loop()
    try:
        path = await loop.run_in_executor(
            None, lambda: ref_media.resolve_file(project_path, rel_path, name)
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@router.post("/{project}/ref/export")
async def export_ref(project: str, payload: RefExport) -> dict:
    """Copy a ref file to a user-chosen destination (download button)."""
    _ensure_project(project)
    project_path = get_project_path(project)
    loop = asyncio.get_event_loop()
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

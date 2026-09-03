# routers/production.py — Production Tab endpoints.
#
# GET  /production/{project}                  read + reconcile against activite.json
# PUT  /production/{project}                  replace production.json (debounced by front)
# POST /production/{project}/materialize      create the disk folder for an entity

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core import config
from core.constants import DEFAULT_TYPE_TOKENS
from core.logger import get_logger
from core.paths import get_project_path
from features.activity.activity_reader import get_all_events
from features.activity.activity_writer import log_event
from features.folder_manager.asset_creator import create_asset as folder_create_asset
from features.folder_manager.seq_shot_creator import (
    create_sequence, create_shot, update_sequence, update_shot,
)
from features.folder_manager.tokens import load_tokens
from core.constants import DEFAULT_CLASS_TOKENS
from features.production import production_store as store
from features.production.disk_scan import scan_project_assets, scan_project_shots
from features.production.reconcile import reconcile
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


class MaterializePayload(BaseModel):
    kind: str                    # "asset" | "sequence" | "shot"
    class_token: str | None = None   # asset only (CHAR / PROPS / ENV / FXRIG…)
    name: str | None = None          # asset name
    seq_number: int | None = None    # sequence / shot
    shot_number: int | None = None   # shot
    # When True, use the idempotent path (skip if exists, add missing shots for
    # a sequence). Also accepted implicitly whenever the target already exists.
    update: bool = False
    # For a sequence materialize, the shot numbers to ensure exist under it.
    shot_numbers: list[int] | None = None


def _ensure_project(project: str) -> None:
    if not project_utils.project_exists(project):
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")


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
    """Replace production.json with *payload.production* (atomic)."""
    _ensure_project(project)
    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, lambda: store.save_production(project, payload.production))
    if not ok:
        raise HTTPException(status_code=500, detail="Écriture production.json échouée")
    return {"success": True}


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


@router.post("/{project}/materialize")
async def materialize(project: str, payload: MaterializePayload) -> dict:
    """Create the on-disk folder for an entity that only exists as planning."""
    _ensure_project(project)
    loop = asyncio.get_event_loop()
    project_path = get_project_path(project)

    kind = payload.kind.lower()

    def _mat() -> dict:
        if kind == "asset":
            if not payload.class_token or not payload.name:
                raise ValueError("class_token et name requis pour un asset")
            path = folder_create_asset(project_path, payload.class_token.upper(), payload.name.upper())
            return {"kind": "asset", "path": str(path)}
        if kind == "sequence":
            if payload.seq_number is None:
                raise ValueError("seq_number requis pour une séquence")
            # Sequence materialize now always ensures the listed shots too
            # (never overwrites — only creates what is missing).
            path = update_sequence(project_path, payload.seq_number, payload.shot_numbers or [])
            return {"kind": "sequence", "path": str(path)}
        if kind == "shot":
            if payload.seq_number is None or payload.shot_number is None:
                raise ValueError("seq_number et shot_number requis pour un shot")
            if payload.update:
                path = update_shot(project_path, payload.seq_number, payload.shot_number)
            else:
                path = create_shot(project_path, payload.seq_number, payload.shot_number)
            return {"kind": "shot", "path": str(path)}
        raise ValueError(f"kind inconnu : {payload.kind!r}")

    try:
        result = await loop.run_in_executor(None, _mat)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        log.exception("Materialize failed")
        raise HTTPException(status_code=500, detail=str(e))
    return {"success": True, **result}


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

"""
FLUX Work routes (ADR 0051): versions of a Houdini work subnet, called by the FLUX Work
HDA. Metadata only: Houdini writes the .cpio itself (ADR 0005).
Mounted at /dcc/houdini/work.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from core.logger import get_logger
from features.houdini_work import work_store

log = get_logger(__name__)
router = APIRouter()

# Departments a FLUX Work can open (ADR 0051), in menu order; kept only when the
# project's TYPE_SHOT tokens know them.
WORK_TASKS = ("CFX", "FX", "LIGHT", "RENDER")


class TaskRef(BaseModel):
    project: str
    seq: str
    shot: str = ""            # empty = sequence task
    task: str


class ReserveRequest(TaskRef):
    author: str = ""
    host: str = ""
    based_on: str = ""
    comment: str = ""
    houdini_version: str = ""
    license: str = ""
    category: str = ""        # Sop | Lop
    template: bool = False


class CommitRequest(TaskRef):
    version: str
    hash: str = ""
    size: int = 0
    node_types: list = []
    external_deps: list = []
    embedded_hdas: list = []
    render_blocks: list | None = None    # RENDER: base of the Timeline sync


class RenderPlanRequest(TaskRef):
    base_version: str = ""
    blocks: list = []                     # [{block, shot, range}] of the scene


class RenderApplyRequest(TaskRef):
    push: list = []
    create: list = []


class VersionRequest(TaskRef):
    version: str


class LockRequest(TaskRef):
    author: str = ""
    host: str = ""
    force: bool = False


def _project_path(project: str):
    from core.paths import get_project_path

    path = get_project_path(project)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Projet introuvable : {project}")
    return path


def _folder(ref: TaskRef):
    try:
        return work_store.work_dir(_project_path(ref.project), ref.seq, ref.shot, ref.task)
    except work_store.WorkError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _author(author: str) -> str:
    from core.config import get_current_user

    return author or get_current_user() or ""


async def _run(fn):
    try:
        return await asyncio.get_running_loop().run_in_executor(None, fn)
    except work_store.WorkError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/tasks")
async def work_tasks(project: str, category: str = "") -> dict:
    """Departments a FLUX Work can open in this project; *category* (Sop / Lop) keeps
    the ones whose content lives in that network."""
    from features.folder_manager.tokens import load_tokens

    known = (load_tokens(_project_path(project)) or {}).get("TYPE_SHOT") or {}
    tasks = [t for t in WORK_TASKS if t in known]
    if category:
        tasks = [t for t in tasks if work_store.TASK_CATEGORY.get(t, "").lower() == category.lower()]
    return {"tasks": tasks, "categories": {t: work_store.TASK_CATEGORY.get(t, "") for t in tasks}}


def _render_setup(project_path, project: str, seq: str, shot: str) -> dict:
    """What FLUX fills after loading the RENDER template (same steps as the render scene
    of ADR 0037): FLUX Sequence, shot blocks, each block's imports and FLUX Render,
    the project resolution."""
    from dcc.houdini.hda.flux_sequence_hda import MODULE_FUNCTIONS
    from features.folder_manager import houdini_render_scene as rs

    from features.houdini_work import render_sync
    from features.production import production_store

    ranges = render_sync.production_ranges(production_store.load_production(project), seq)
    shots = [{"shot": shot.upper()}] if shot else rs.sequence_shots(project_path, seq)
    for item in shots:
        rng = ranges.get(str(item.get("shot", "")).upper())
        item["range"] = list(rng) if rng else None
    return {"kind": "render_sequence", "project": project, "seq": seq.upper(), "shots": shots,
            "blocks": max(rs.MIN_SHOT_BLOCKS, len(shots)), "resolution": rs._resolution(project_path),
            "sequence_module": MODULE_FUNCTIONS}


@router.get("/template")
async def work_template(project: str, task: str, seq: str = "", shot: str = "") -> dict:
    """Source of the w000 of a task: the project's template cpio, else FLUX's, else none
    (the Work builds its default content). RENDER also gets its setup plan."""
    project_path = _project_path(project)
    path, source = work_store.template_cpio(project_path, task)
    setup = None
    if task.strip().upper() == "RENDER" and seq.strip():
        setup = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _render_setup(project_path, project, seq, shot))
    return {"cpio": str(path).replace("\\", "/") if path else "", "source": source,
            "category": work_store.TASK_CATEGORY.get(task.strip().upper(), ""), "setup": setup}


@router.get("/module")
async def work_module() -> dict:
    """PythonModule of the FLUX Work HDA, exec()'d by its bootstrap (no rebuild on fix)."""
    from dcc.houdini.hda.flux_work_hda import module_code

    return {"code": module_code()}


@router.get("/shots")
async def work_shots(project: str) -> dict:
    """Sequences of the Production planning and their shots, for the FLUX Work menus."""
    from features.production import production_store

    _project_path(project)
    production = await asyncio.get_running_loop().run_in_executor(
        None, lambda: production_store.load_production(project))
    names = {s.get("id"): str(s.get("name") or "").upper() for s in production.get("sequences", [])}
    out: dict[str, list[str]] = {name: [] for name in names.values() if name}
    for shot in production.get("shots", []):
        seq = names.get(shot.get("seq_id"))
        name = str(shot.get("name") or "").upper()
        if seq and name:
            out.setdefault(seq, []).append(name)
    return {"sequences": [{"seq": seq, "shots": sorted(shots)} for seq, shots in sorted(out.items())]}


@router.get("/status")
async def work_status(project: str, seq: str, task: str, shot: str = "", based_on: str = "",
                      author: str = "", host: str = "") -> dict:
    folder = _folder(TaskRef(project=project, seq=seq, shot=shot, task=task))
    return await _run(lambda: work_store.task_status(folder, based_on=based_on,
                                                     author=_author(author), host=host))


@router.post("/reserve")
async def work_reserve(req: ReserveRequest) -> dict:
    folder = _folder(req)
    return await _run(lambda: work_store.reserve_version(
        folder, author=_author(req.author), host=req.host, based_on=req.based_on,
        comment=req.comment, houdini_version=req.houdini_version, license=req.license,
        category=req.category, seq=req.seq.upper(), shot=req.shot.upper(), task=req.task.upper(),
        template=req.template))


@router.post("/commit")
async def work_commit(req: CommitRequest) -> dict:
    folder = _folder(req)
    return await _run(lambda: work_store.commit_version(
        folder, req.version, hash=req.hash, size=req.size, node_types=req.node_types,
        external_deps=req.external_deps, embedded_hdas=req.embedded_hdas,
        render_blocks=req.render_blocks))


@router.post("/abort")
async def work_abort(req: VersionRequest) -> dict:
    folder = _folder(req)
    return {"removed": await _run(lambda: work_store.abort_version(folder, req.version))}


@router.post("/lock")
async def work_lock(req: LockRequest) -> dict:
    folder = _folder(req)
    return await _run(lambda: work_store.take_lock(folder, author=_author(req.author),
                                                   host=req.host, force=req.force))


@router.post("/unlock")
async def work_unlock(req: LockRequest) -> dict:
    folder = _folder(req)
    return {"released": await _run(lambda: work_store.release_lock(
        folder, author=_author(req.author), host=req.host))}


# ── RENDER <-> Production Timeline (features/houdini_work/render_sync.py) ─────────

@router.post("/render-sync/plan")
async def render_sync_plan(req: RenderPlanRequest) -> dict:
    """Three-way compare scene / base version / Production for the render Work."""
    from features.houdini_work import render_sync
    from features.production import production_store

    folder = _folder(req)
    base_blocks = None
    if req.base_version:
        manifest = next((v for v in work_store.list_versions(folder) if v["version"] == req.base_version), None)
        if manifest is not None and "render_blocks" in manifest:
            base_blocks = manifest.get("render_blocks") or []
    production = await asyncio.get_running_loop().run_in_executor(
        None, lambda: production_store.load_production(req.project))
    return render_sync.plan(req.blocks, base_blocks, production, req.seq)


@router.post("/render-sync/apply")
async def render_sync_apply(req: RenderApplyRequest) -> dict:
    """Write the pushed ranges / created shots into Production through the normal save
    (stages regenerated, open Houdini notified, folders of new shots created)."""
    from features.houdini_work import render_sync
    from features.production import production_store
    from routers.production import ProductionPayload, put_production

    _project_path(req.project)
    production = await asyncio.get_running_loop().run_in_executor(
        None, lambda: production_store.load_production(req.project))
    try:
        done = render_sync.apply(production, req.seq, req.push, req.create)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if done["updated"] or done["created"]:
        saved = await put_production(req.project, ProductionPayload(production=production))
        done["shot_stages"] = saved.get("shot_stages", [])
    log.info("Render Work -> Production %s %s: %s", req.project, req.seq, done)
    return done
